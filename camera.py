#!/usr/bin/env python

"""Recording script for a Raspberry Pi powered motorcycle helmet camera.
"""

import os
import datetime
import shutil
import subprocess
import logging
import logging.handlers
import time
import pickle
import multiprocessing
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import httplib2
import functools
import socket
try:
  import picamera
except ImportError:
  print('Couldn\'t import picamera: running as is for debug purposes.')

formatter = logging.Formatter('%(asctime)s [%(processName)s] [%(levelname)-5.5s] %(message)s')

rootLogger = logging.getLogger()
rootLogger.setLevel(logging.DEBUG)
fileHandler = logging.handlers.RotatingFileHandler(
  filename=os.path.join(os.path.dirname(__file__), 'camera.log'),
  maxBytes=0.1 * (10 ** 6), backupCount=5)
fileHandler.setFormatter(formatter)
rootLogger.addHandler(fileHandler)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(formatter)
rootLogger.addHandler(consoleHandler)

logging.getLogger('googleapiclient.discovery').setLevel(logging.CRITICAL)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.CRITICAL)

VIDEODIR = os.path.join(os.path.dirname(__file__), 'video')
CREDENTIALS = os.path.join(os.path.dirname(__file__), '.credentials')
FORMAT = 'h264'
MAX_VIDEO_SIZE = 500 * (10 ** 6)
MIN_VIDEO_SIZE = 50 * (10 ** 6)  # ~30 seconds

# how many 0s to put in front of counter number
ZFILL_DECIMAL = 3

# 8mp V2 camera
RESOLUTION = (1640, 1232)
FRAMERATE = 30
STABILIZATION = False

# number of seconds to flush on disk
INTERVAL = 1

# check for enough disk space every N seconds
SPACE_CHECK_INTERVAL = 30

# what % of disk space must be free to start a new video
REQUIRED_FREE_SPACE_PERCENT = 15  # about an hour with 64gb card

YOUTUBE_TITLE_PREFIX = 'Helmet Camera'

queue = []


class throttle(object):
  """Decorator that prevents a function from being called more than once every
  time period.

  To create a function that cannot be called more than once a minute:
    @throttle(minutes=1)
    def my_fun():
      pass
  """
  def __init__(self, seconds=0, minutes=0, hours=0):
    self.throttle_period = datetime.timedelta(
      seconds=seconds, minutes=minutes, hours=hours)
    self.time_of_last_call = datetime.datetime.min

  def __call__(self, fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
      now = datetime.datetime.now()
      time_since_last_call = now - self.time_of_last_call
      if time_since_last_call > self.throttle_period:
        self.time_of_last_call = now
        self.last_result = fn(*args, **kwargs)
        return self.last_result
      else:
        return self.last_result
    return wrapper


@throttle(seconds=5)
def is_connected(host='8.8.8.8', port=53, timeout=1):
  """Returns True if we have internet connection.
  """
  try:
    socket.setdefaulttimeout(timeout)
    socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
    result = True
  except socket.error:
    result = False
  finally:
    socket.setdefaulttimeout(None)
    return result


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
  title = '%s %s' % (
    YOUTUBE_TITLE_PREFIX,
    ':'.join(os.path.split(filename)[1][:-12].replace('_', ' ').rsplit('-', 1)))
  body = dict(snippet=dict(title=title, tags=['helmet'], categoryId=2),
              status=dict(privacyStatus='unlisted'))
  logging.debug('Preparing to upload %s...', filename)
  try:
    result = service.videos().insert(
      part=','.join(body.keys()),
      body=body,
      media_body=MediaFileUpload(filename, chunksize=-1, resumable=True)
    ).execute()
  except httplib2.ServerNotFoundError:
    logging.debug('Couldn\'t upload %s since no connection is available.')
  else:
    logging.debug('Successfully uploaded %s', result)
    os.remove(filename)


def watch():
  """Background watcher which removes old videos and tries to perform an upload.
  """
  while True:
    while not enough_disk_space():
      make_room()
    for i in reversed([i for i, p in enumerate(queue) if not p.is_alive()]):
      queue.pop(i)
    logging.debug('Upload queue: %s', queue)

    if is_connected():
      for video in sorted(os.listdir(VIDEODIR)):
        filename = os.path.join(VIDEODIR, video)
        if filename in [i.name for i in queue]:
          continue
        if os.stat(filename).st_size < MIN_VIDEO_SIZE:
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


def record():
  """Start recording after no connection is avilable and stop when connected.
  """
  while is_connected():
    logging.debug('Still connected...')
    time.sleep(5)
  with picamera.PiCamera() as camera:
    camera.resolution = RESOLUTION
    camera.framerate = FRAMERATE
    camera.video_stabilization = STABILIZATION
    logging.debug('Recording with %s@%s FPS', RESOLUTION, FRAMERATE)
    camera.annotate_background = picamera.Color('black')
    counter = 0
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
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
      if is_connected():
        logging.info('Connected to WiFi. Not recording anymore.')
        camera.stop_recording()
        shard.close()
        break
  logging.info('Trying to start recording again...')
  record()


def main():
  if not os.path.isdir(VIDEODIR):
    logging.debug('Creating directory %s', VIDEODIR)
    os.mkdir(VIDEODIR)
  p = multiprocessing.Process(target=watch, name='watcher')
  logging.debug('Starting background process %s', p)
  p.start()
  record()


if __name__ == '__main__':
  try:
    main()
  except KeyboardInterrupt:
    exit('Command killed by keyboard interrupt')
