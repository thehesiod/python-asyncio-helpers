import asyncio
import aiohttp
import functools
import logging
import flask
import os
import threading
import moto.server
import socket
import netifaces
import wrapt
import http.server
from typing import Dict, Any


def get_free_tcp_port(release_socket=False):
    sckt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sckt.bind(('', 0))
    addr, port = sckt.getsockname()
    if release_socket:
        sckt.close()
        return port

    return sckt, port


# AMI, OSX
local_ifaces = ['eth0', 'en0']


def get_ip_address():
    ifaces = netifaces.interfaces()
    for iface in local_ifaces:
        if iface in ifaces:
            iface = netifaces.ifaddresses(iface)

            if netifaces.AF_INET in iface:
                assert len(iface[netifaces.AF_INET]) == 1
                ip_address = iface[netifaces.AF_INET][0]['addr']
                return ip_address

    assert False


# Enable keep-alive
http.server.BaseHTTPRequestHandler.protocol_version = "HTTP/1.1"


class MotoService:
    """ Will Create MotoService.

    Service is ref-counted so there will only be one per process. Real Service will
    be returned by `__aenter__`."""

    _services: Dict[str, Any] = dict()  # {name: instance}

    def __init__(self, service_name: str, port: int=None):
        self._service_name = service_name

        if port:
            self._socket = None
            self._port = port
        else:
            self._socket, self._port = get_free_tcp_port()

        self._thread = None
        self._logger = logging.getLogger('MotoService')
        self._refcount = None
        self._ip_address = get_ip_address()

    @property
    def endpoint_url(self):
        return 'http://{}:{}'.format(self._ip_address, self._port)

    def __call__(self, func):
        async def wrapper(*args, **kwargs):
            await self._start()
            try:
                result = await func(*args, **kwargs)
            finally:
                await self._stop()
            return result

        functools.update_wrapper(wrapper, func)
        wrapper.__wrapped__ = func
        return wrapper

    async def __aenter__(self):
        svc = self._services.get(self._service_name)
        if svc is None:
            self._services[self._service_name] = self
            self._refcount = 1
            await self._start()
            return self
        else:
            svc._refcount += 1
            return svc

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._refcount -= 1

        if self._socket:
            self._socket.close()
            self._socket = None

        if self._refcount == 0:
            del self._services[self._service_name]
            await self._stop()

    @staticmethod
    def _shutdown():
        req = flask.request
        shutdown = req.environ['werkzeug.server.shutdown']
        shutdown()
        return flask.make_response('done', 200)

    def _create_backend_app(self, *args, **kwargs):
        backend_app = moto.server.create_backend_app(*args, **kwargs)
        backend_app.add_url_rule('/shutdown', 'shutdown', self._shutdown)
        return backend_app

    def _server_entry(self):
        self._main_app = moto.server.DomainDispatcherApplication(self._create_backend_app, service=self._service_name)
        self._main_app.debug = True

        if self._socket:
            self._socket.close()  # release right before we use it
            self._socket = None

        moto.server.run_simple(self._ip_address, self._port, self._main_app, threaded=True)

    async def _start(self):
        self._thread = threading.Thread(target=self._server_entry, daemon=True)
        self._thread.start()

        async with aiohttp.ClientSession() as session:
            for i in range(0, 10):
                if not self._thread.is_alive():
                    break

                try:
                    # we need to bypass the proxies due to monkeypatches
                    async with session.get(self.endpoint_url + '/static/', timeout=0.5):
                        pass
                    break
                except (asyncio.TimeoutError, aiohttp.ClientConnectionError):
                    await asyncio.sleep(0.5)
            else:
                await self._stop()  # pytest.fail doesn't call stop_process
                raise Exception("Can not start service: {}".format(self._service_name))

    async def _stop(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.endpoint_url + '/shutdown', timeout=5):
                    pass
        except:
            self._logger.exception("Error stopping moto service")
            raise
        finally:
            self._thread.join()


def _wrapt_boto_create_client(wrapped, instance, args, kwargs):
    def unwrap_args(service_name, region_name=None, api_version=None,
                    use_ssl=True, verify=None, endpoint_url=None,
                    aws_access_key_id=None, aws_secret_access_key=None,
                    aws_session_token=None, config=None):

        if endpoint_url is None:
            endpoint_url = os.environ.get('{}_mock_endpoint_url'.format(service_name))

        return wrapped(service_name, region_name, api_version, use_ssl, verify,
                       endpoint_url, aws_access_key_id, aws_secret_access_key,
                       aws_session_token, config)

    return unwrap_args(*args, **kwargs)


def patch_boto():
    """
    Will patch botocore to set endpoint_url to: {SERVICE_NAME}_endpoint_url if
    available
    """
    wrapt.wrap_function_wrapper(
        'botocore.session',
        'Session.create_client',
        _wrapt_boto_create_client
    )
