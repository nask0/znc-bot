from urllib.parse import urlparse, urlencode
import json
from xml.etree import ElementTree

import znc

HTTP_STATES = {
    'AWAITING_CONNECTION': 0,
    'CONNECTED': 1,
    'DISCONNECTED': 2,
    'HEADERS': 3,
    'BODY': 4,
}

class HttpResponse(object):
    def __init__(self, status_code, content='', headers={}):
        self.status_code = status_code
        self.content = content
        self.headers = headers

    def is_redirect(self):
        return (self.status_code == 301 or self.status_code == 302) and 'Location' in self.headers

    def __str__(self):
        return self.content

    def __repr__(self):
        return '<HttpResponse {} ({})>'.format(self.status_code, self.headers)


class HttpSock(znc.Socket):
    HTTP_STATES = {
        'AWAITING_CONNECTION': 0,
        'CONNECTED': 1,
        'DISCONNECTED': 2,
        'HEADERS': 3,
        'BODY': 4,
    }

    def Init(self, url, qs=None, data=None, method=None, headers={}, timeout=10, callback=None, args=[], kwargs={}):
        self.state = HTTP_STATES['AWAITING_CONNECTION']

        o = urlparse(url)
        self.headers = headers
        self.path = o.path
        self.qs = qs
        self.data = data

        self.callback = callback
        self.args = args
        self.kwargs = kwargs

        if method:
            self.method = method.upper()
        else:
            if self.data:
                self.method = 'POST'
            else:
                self.method = 'GET'

        if 'Host' not in headers:
            self.headers['Host'] = o.hostname

        if 'User-Agent' not in headers:
            self.headers['User-Agent'] = 'Mozilla/5.0 ({})'.format(znc.CZNC.GetTag())

        if o.query and not self.qs: # Use ?bla=foo in url if its provided
            self.qs = o.query

        # urlparse could give blank paths if we didn't provide one in the url.
        if len(self.path) == 0:
            self.path = '/'

        # urlparse will not give us a port unless we specified one in the url.
        port = o.port
        if not port:
            if o.scheme == 'https':
                port = 443
            elif o.scheme == 'http':
                port = 80
            else:
                raise Exception("Unsupported scheme: {}".format(o.scheme))

        self.EnableReadLine()
        self.Connect(o.hostname, port, timeout=timeout, ssl=(o.scheme == 'https'))

    def OnConnected(self):
        self.state = HTTP_STATES['CONNECTED']

        if self.qs:
            path = '{}?{}'.format(self.path, urlencode(self.qs))
        else:
            path = self.path

        self.Write("{} {} HTTP/1.0\r\n".format(self.method, path))

        if self.data:
            data_string = urlencode(self.data)
            self.headers['Conent-Length'] = len(data_string)

        for k,v in self.headers.items():
            self.Write("{}: {}\r\n".format(k, v))

        self.Write("\r\n")

        if self.data:
            self.Write("{}\r\n".format(data_string))

    def OnReadLine(self, line):
        line = line.strip()

        if self.state == HTTP_STATES['CONNECTED']: # HTTP/ver status_code status message
            self.state = HTTP_STATES['HEADERS']
            self.response = HttpResponse(int(line.split()[1]))
        elif self.state == HTTP_STATES['HEADERS']: # Key: Value
            if len(line) == 0:
                self.state = HTTP_STATES['BODY']
            else:
                key, value = line.split(': ')
                self.response.headers[key] = value
        elif self.state == HTTP_STATES['BODY']:
            self.response.content += line

    def OnDisconnected(self):
        buf = self.GetInternalReadBuffer()
        if buf.s:
            self.OnReadLine(str(buf.s))

        self.state = HTTP_STATES['DISCONNECTED']

        if self.callback:
            self.OnCallback()

    def OnCallback(self):
        self.callback(self, self.response, *self.args, **self.kwargs)


class JsonHttpSock(HttpSock):
    def OnCallback(self):
        if self.response.status_code == 200:
            self.callback(self, self.response, json.loads(self.response.content), *self.args, **self.kwargs)

class XmlHttpSock(HttpSock):
    def OnCallback(self):
        if self.response.status_code == 200:
            self.callback(self, self.response, ElementTree.fromstring(self.response.content), *self.args, **self.kwargs)