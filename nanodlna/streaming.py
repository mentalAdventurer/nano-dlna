#!/usr/bin/env python3
# encoding: UTF-8

import os
import socket
import threading
import unicodedata
import re
import mimetypes

from twisted.internet import reactor
from twisted.web.resource import Resource
from twisted.web.server import Site
from twisted.web.static import File

import logging
import json

# from twisted.python import log


DLNA_FLAGS = "01700000000000000000000000000000"
DLNA_PROTOCOL_BY_EXTENSION = {
    ".avi": "DLNA.ORG_PN=AVI",
    ".m4v": "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520",
    ".mkv": "DLNA.ORG_PN=MATROSKA",
    ".mov": "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520",
    ".mp4": "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520",
}


def normalize_file_name(value):
    value = unicodedata\
        .normalize("NFKD", value)\
        .encode("ascii", "ignore")\
        .decode("ascii")
    value = re.sub(r"[^\.\w\s-]", "", value.lower())
    value = re.sub(r"[-\s]+", "-", value).strip("-_")
    return value


def build_content_features(file_path):
    extension = os.path.splitext(file_path)[1].lower()
    mime_type = (
        mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    )
    dlna_profile = DLNA_PROTOCOL_BY_EXTENSION.get(extension)

    attributes = []
    if dlna_profile:
        attributes.append(dlna_profile)
    attributes.extend([
        "DLNA.ORG_OP=01",
        "DLNA.ORG_CI=0",
        "DLNA.ORG_FLAGS={0}".format(DLNA_FLAGS)
    ])

    return "http-get:*:{0}:{1}".format(mime_type, ";".join(attributes))


class StreamingFile(File):

    def __init__(self, path, defaultType="application/octet-stream"):
        File.__init__(self, path, defaultType=defaultType)
        self.content_features = build_content_features(path)

    def _set_stream_headers(self, request):
        request.setHeader(b"Accept-Ranges", b"bytes")
        request.setHeader(
            b"contentFeatures.dlna.org",
            self.content_features.encode("utf-8")
        )
        request.setHeader(b"transferMode.dlna.org", b"Streaming")

    def render(self, request):
        self._set_stream_headers(request)
        return File.render(self, request)


def set_files(files, serve_ip, serve_port):

    logging.debug("Setting streaming files: {}".format(
        json.dumps({
            "files": files,
            "serve_ip": serve_ip,
            "serve_port": serve_port
        })
    ))

    files_index = {file_key: (normalize_file_name(os.path.basename(file_path)),
                              os.path.abspath(file_path),
                              os.path.dirname(os.path.abspath(file_path)))
                   for file_key, file_path in files.items()}

    files_serve = {file_name: file_path
                   for file_name, file_path, file_dir in files_index.values()}

    files_urls = {
        file_key: "http://{0}:{1}/{2}/{3}".format(
            serve_ip, serve_port, file_key, file_name)
        for file_key, (file_name, file_path, file_dir)
        in files_index.items()}

    logging.debug("Streaming files information: {}".format(
        json.dumps({
            "files_index": files_index,
            "files_serve": files_serve,
            "files_urls": files_urls
        })
    ))

    return files_index, files_serve, files_urls


def start_server(files, serve_ip, serve_port=9000):

    # import sys
    # log.startLogging(sys.stdout)

    logging.debug("Starting to create streaming server")

    files_index, files_serve, files_urls = set_files(
        files, serve_ip, serve_port)

    logging.debug("Adding files to HTTP server")
    root = Resource()
    for file_key, (file_name, file_path, file_dir) in files_index.items():
        root.putChild(file_key.encode("utf-8"), Resource())
        root.children[file_key.encode("utf-8")].putChild(
            file_name.encode("utf-8"), StreamingFile(file_path))

    logging.debug("Starting to listen messages in HTTP server")
    reactor.listenTCP(serve_port, Site(root))
    threading.Thread(
        target=reactor.run, kwargs={"installSignalHandlers": False}).start()

    return files_urls


def stop_server():
    reactor.stop()


def get_serve_ip(target_ip, target_port=80):
    logging.debug("Identifying server IP")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((target_ip, target_port))
    serve_ip = s.getsockname()[0]
    s.close()
    logging.debug("Server IP identified: {}".format(serve_ip))
    return serve_ip


if __name__ == "__main__":

    import sys

    files = {"file_{0}".format(i): file_path for i,
             file_path in enumerate(sys.argv[1:], 1)}
    print(files)

    files_urls = start_server(files, "localhost")
    print(files_urls)
