#!/usr/bin/env python

"""Recording script for a Raspberry Pi powered motorcycle helmet camera.
"""

import picamera
import datetime
import os
import shutil
import sys
import subprocess
import logging
import time
import pickle
import multiprocessing
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import httplib2


VIDEODIR = os.path.join(os.path.dirname(__file__), 'video')
CREDENTIALS = os.path.join(os.path.dirname(__file__), '.credentials')
FORMAT = 'h264'
MAX_VIDEO_SIZE = 500 * (10 ** 6)

# how many 0s to put in front of counter number
ZFILL_DECIMAL = 3

# 8mp V2 camera
RESOLUTION = (1640, 1232)
FRAMERATE = 30

# number of seconds to flush on disk
INTERVAL = 1

# check for enough disk space every N seconds
SPACE_CHECK_INTERVAL = 60

# what % of disk space must be free to start a new video
REQUIRED_FREE_SPACE_PERCENT = 15  # about an hour with 64gb card

queue = []


def make_room():
  """Clear oldest video.
  """
  sorted_videos = sorted(os.listdir(VIDEODIR))
  if sorted_videos:
    oldest_video = sorted_videos[0]
    logging.debug('Removing oldest video: %s', oldest_video)
    # may not have permission if running as pi and video was created by root
    try:
      shutil.rmtree(os.path.join(VIDEODIR, oldest_video))
    except OSError:
      logging.error('Must run as root otherwise script cannot clear out old videos')
      exit(1)
  else:
    logging.debug('No videos in directory %s, cannot make room', VIDEODIR)


def enough_disk_space():
  """Return true if we have enough space to start a new video.
  """
  df = subprocess.Popen(['df', '/'], stdout=subprocess.PIPE)
  output = df.communicate()[0]
  percent_used_str = output.split("\n")[1].split()[4]
  percent_used = int(percent_used_str.replace('%', ''))
  logging.debug('%s%% of disk space used.', percent_used)
  enough = 100 >= REQUIRED_FREE_SPACE_PERCENT + percent_used
  logging.debug('Enough space to start new video: %s', enough)
  return enough


def upload(filename):
  """Upload given filename on YouTube using saved credentials.

  Raises:
    httplib2.ServerNotFoundError: When no connection is available.
  """
  try:
    credentials = pickle.load(open(CREDENTIALS))
  except IOError:
    logging.error('Unable to read .credentials file to perform youtube upload.')
    return
  service = build('youtube', 'v3', credentials=credentials)
  body = dict(snippet=dict(title=filename, tags=['helmet'], categoryId=2),
              status=dict(privacyStatus='unlisted'))
  logging.debug('Preparing to upload %s...', filename)
  result = service.videos().insert(
    part=','.join(body.keys()),
    body=body,
    media_body=MediaFileUpload(filename, chunksize=-1, resumable=True)
  ).execute()
  logging.debug('Successfully uploaded %s', result)
  os.remove(filename)


def watch():
  """Background watcher which removes old videos and tries to perform an upload.

  Will try to upload all but the last video, since we are still recording it.
  """
  while True:
    while not enough_disk_space():
      make_room()
    for i in reversed([i for i, p in enumerate(queue) if not p.is_alive()]):
      queue.pop(i)
    logging.debug('Upload queue: %s', queue)
    for video in sorted(os.listdir(VIDEODIR))[:-1]:
      filename = os.path.join(VIDEODIR, video)
      if filename in [i.name for i in queue]:
        continue
      p = multiprocessing.Process(target=upload, name=filename, args=[filename])
      logging.debug('Starting background process %s', p)
      p.start()
      queue.append(p)
    time.sleep(SPACE_CHECK_INTERVAL)


class OutputShard(object):
  def __init__(self, filename):
    self.filename = filename
    self.stream = open(filename, 'ab')

  def write(self, buf):
    self.stream.write(buf)

  def close(self):
    self.stream.close()

  @property
  def size(self):
    return os.stat(self.filename).st_size


def main():
  p = multiprocessing.Process(target=watch)
  logging.debug('Starting background process %s', p)
  p.start()
  with picamera.PiCamera() as camera:
    camera.resolution = RESOLUTION
    camera.framerate = FRAMERATE
    logging.debug('Recording with %s@%s FPS', RESOLUTION, FRAMERATE)
    camera.annotate_background = picamera.Color('black')
    counter = 0
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    if not os.path.isdir(VIDEODIR):
      logging.debug('Creating directory %s', VIDEODIR)
      os.mkdir(VIDEODIR)
    filename = os.path.join(VIDEODIR, '%s.{}.%s' % (timestamp, FORMAT))
    shard = OutputShard(filename.format(str(counter).zfill(ZFILL_DECIMAL)))
    camera.start_recording(shard, format=FORMAT, intra_period=INTERVAL * FRAMERATE)
    while True:
      camera.annotate_text = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
      camera.split_recording(shard)
      camera.wait_recording(INTERVAL)
      if shard.size > MAX_VIDEO_SIZE:
        counter += 1
        logging.debug('Using next shard %s for video file', counter)
      shard = OutputShard(filename.format(str(counter).zfill(ZFILL_DECIMAL)))


if __name__ == '__main__':
  if len(sys.argv) > 1:
    if sys.argv[1] == '-d' or sys.argv[1] == '--debug':
      logging.basicConfig(level=logging.DEBUG)

  try:
    main()
  except KeyboardInterrupt:
    exit('Command killed by keyboard interrupt')
