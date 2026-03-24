#!/usr/bin/env python3
# encoding: UTF-8

import mimetypes
import os
import pkgutil
import subprocess
import sys
from xml.sax.saxutils import escape as xmlescape

if sys.version_info.major == 3:
    import urllib.request as urllibreq
else:
    import urllib2 as urllibreq

import traceback
import logging
import json


DLNA_FLAGS = "01700000000000000000000000000000"
DLNA_PROTOCOL_BY_EXTENSION = {
    ".avi": "DLNA.ORG_PN=AVI",
    ".m4v": "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520",
    ".mkv": "DLNA.ORG_PN=MATROSKA",
    ".mov": "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520",
    ".mp4": "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520",
}


def send_dlna_action(device, data, action):

    logging.debug("Sending DLNA Action: {}".format(
        json.dumps({
            "action": action,
            "device": device,
            "data": data
        })
    ))

    action_data = pkgutil.get_data(
        "nanodlna", "templates/action-{0}.xml".format(action)).decode("UTF-8")
    if data:
        action_data = action_data.format(**data)
    action_data = action_data.encode("UTF-8")

    headers = {
        "Content-Type": "text/xml; charset=\"utf-8\"",
        "Content-Length": "{0}".format(len(action_data)),
        "Connection": "close",
        "SOAPACTION": "\"{0}#{1}\"".format(device["st"], action)
    }

    logging.debug("Sending DLNA Request: {}".format(
        json.dumps({
            "url": device["action_url"],
            "data": action_data.decode("UTF-8"),
            "headers": headers
        })
    ))

    try:
        request = urllibreq.Request(device["action_url"], action_data, headers)
        urllibreq.urlopen(request)
        logging.debug("Request sent")
    except Exception:
        logging.error("Unknown error sending request: {}".format(
            json.dumps({
                "url": device["action_url"],
                "data": action_data.decode("UTF-8"),
                "headers": headers,
                "error": traceback.format_exc()
            })
        ))


def build_protocol_info(file_path):
    extension = os.path.splitext(file_path)[1].lower()
    mime_type = mimetypes.guess_type(file_path)[0] or "video/mp4"
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


def get_media_duration(file_path):
    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
    except OSError:
        return None

    if process.returncode != 0:
        return None

    try:
        total_seconds = float(process.stdout.strip())
    except ValueError:
        return None

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    return "{0}:{1:02d}:{2:06.3f}".format(hours, minutes, seconds)


def build_video_metadata(files, files_urls):
    file_video = files["file_video"]
    video_url = files_urls["file_video"]
    video_protocol = build_protocol_info(file_video)
    video_duration = get_media_duration(file_video)
    video_mime = mimetypes.guess_type(file_video)[0] or "video/mp4"

    resource_attributes = [
        'protocolInfo="{0}"'.format(xmlescape(video_protocol))
    ]
    if video_duration:
        resource_attributes.append(
            'duration="{0}"'.format(xmlescape(video_duration))
        )

    resources = [
        '<res {0}>{1}</res>'.format(
            " ".join(resource_attributes),
            xmlescape(video_url)
        )
    ]

    if "file_subtitle" in files_urls and files_urls["file_subtitle"]:
        subtitle_type = (
            os.path.splitext(files["file_subtitle"])[1][1:] or "srt"
        )
        subtitle_url = files_urls["file_subtitle"]
        resources[0] = (
            '<res {0} xmlns:pv="http://www.pv.com/pvns/" '
            'pv:subtitleFileUri="{1}" pv:subtitleFileType="{2}">{3}</res>'
        ).format(
            " ".join(resource_attributes),
            xmlescape(subtitle_url),
            xmlescape(subtitle_type),
            xmlescape(video_url)
        )
        resources.extend([
            '<res protocolInfo="http-get:*:text/srt:*">{0}</res>'.format(
                xmlescape(subtitle_url)
            ),
            '<res protocolInfo="http-get:*:smi/caption:*">{0}</res>'.format(
                xmlescape(subtitle_url)
            ),
            '<sec:CaptionInfoEx sec:type="{0}">{1}</sec:CaptionInfoEx>'.format(
                xmlescape(subtitle_type), xmlescape(subtitle_url)
            ),
            '<sec:CaptionInfo sec:type="{0}">{1}</sec:CaptionInfo>'.format(
                xmlescape(subtitle_type), xmlescape(subtitle_url)
            )
        ])

    metadata = """
<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"
    xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/"
    xmlns:sec="http://www.sec.co.kr/">
    <item id="0" parentID="-1" restricted="1">
        <dc:title>{title}</dc:title>
        <upnp:class>object.item.videoItem.movie</upnp:class>
        <upnp:mimeType>{mime_type}</upnp:mimeType>
        {resources}
    </item>
</DIDL-Lite>
""".strip().format(
        title=xmlescape(os.path.basename(file_video)),
        mime_type=xmlescape(video_mime),
        resources="\n        ".join(resources)
    )

    return metadata


def play(files, files_urls, device):

    logging.debug("Starting to play: {}".format(
        json.dumps({
            "files": files,
            "files_urls": files_urls,
            "device": device
        })
    ))

    video_data = {
        "uri_video": files_urls["file_video"],
        "metadata": xmlescape(build_video_metadata(files, files_urls))
    }

    logging.debug("Created video data: {}".format(json.dumps(video_data)))

    logging.debug("Setting Video URI")
    send_dlna_action(device, video_data, "SetAVTransportURI")
    logging.debug("Playing video")
    send_dlna_action(device, video_data, "Play")


def pause(device):
    logging.debug("Pausing device: {}".format(
        json.dumps({
            "device": device
        })
    ))
    send_dlna_action(device, None, "Pause")


def stop(device):
    logging.debug("Stopping device: {}".format(
        json.dumps({
            "device": device
        })
    ))
    send_dlna_action(device, None, "Stop")


def seek(device, target, unit="ABS_TIME"):
    logging.debug("Seeking device: {}".format(
        json.dumps({
            "device": device,
            "target": target,
            "unit": unit
        })
    ))
    send_dlna_action(device, {
        "target": target,
        "unit": unit
    }, "Seek")
