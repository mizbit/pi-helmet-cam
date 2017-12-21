#!/usr/bin/env python

"""Recording script for a Raspberry Pi powered motorcycle helmet camera.
"""

import os
import json
import datetime
import subprocess
import logging
import logging.handlers
import time
import pickle
import multiprocessing
import googleapiclient.discovery
import googleapiclient.http
import googleapiclient.model
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
  maxBytes=0.5 * (10 ** 6), backupCount=1)
fileHandler.setFormatter(formatter)
rootLogger.addHandler(fileHandler)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(formatter)
rootLogger.addHandler(consoleHandler)

logging.getLogger('googleapiclient.discovery').setLevel(logging.CRITICAL)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.CRITICAL)

VIDEO_DIR = os.path.join(os.path.dirname(__file__), 'video')
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
CREDENTIALS = os.path.join(os.path.dirname(__file__), '.credentials')
FORMAT = 'h264'
MAX_VIDEO_SIZE = 5000 * (10 ** 6)  # ~45 minutes
MIN_VIDEO_SIZE = 50 * (10 ** 6)  # ~30 seconds
VIDEO_MIN_INTERVALS = 60

UPLOAD_CHUNK_SIZE = 50 * (10 ** 6)
UPLOAD_MAX_WORKERS = 2

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

DATE_FORMAT = '%Y-%m-%d_%H-%M'

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
  sorted_videos = sorted(os.listdir(VIDEO_DIR))
  if sorted_videos:
    oldest_video = sorted_videos[0]
    logging.debug('Removing oldest video: %s', oldest_video)
    # may not have permission if running as pi and video was created by root
    try:
      os.remove(os.path.join(VIDEO_DIR, oldest_video))
    except OSError:
      logging.error('Must run as root otherwise script cannot clear out old videos')
  else:
    logging.error('No videos in directory %s, cannot make room', VIDEO_DIR)
    time.sleep(SPACE_CHECK_INTERVAL)


@throttle(seconds=SPACE_CHECK_INTERVAL)
def enough_disk_space():
  """Return true if we have enough space to start a new video.
  """
  df = subprocess.Popen(['df', '/'], stdout=subprocess.PIPE)
  output = df.communicate()[0]
  percent_used_str = output.split("\n")[1].split()[4]
  percent_used = int(percent_used_str.replace('%', ''))
  enough = 100 >= REQUIRED_FREE_SPACE_PERCENT + percent_used
  logging.debug('%s%% of disk space used. Enough: %s', percent_used, enough)
  return enough


def upload(filename):
  """Upload given filename on YouTube using saved credentials.

  For each video file we will create a JSON file in `uploads` dir with upload
  progress. This way we can resume upload if it was interrupted and avoid
  duplicates.
  """
  try:
    credentials = pickle.load(open(CREDENTIALS))
  except IOError:
    logging.error('Unable to read .credentials file to perform youtube upload.')
    return
  service = googleapiclient.discovery.build(
    'youtube', 'v3', credentials=credentials)
  name_parts = os.path.split(filename)[1].split('.')
  title = '%s %s' % (
    YOUTUBE_TITLE_PREFIX,
    ':'.join(name_parts[0].replace('_', ' ').rsplit('-', 1)))
  part_num = int(filename.split('.')[1])
  if part_num:
    title = '%s Part %s' % (title, part_num + 1)
  body = dict(snippet=dict(title=title, tags=['helmet'], categoryId=2),
              status=dict(privacyStatus='unlisted'))
  logging.debug('Preparing to upload %s...', filename)
  request = service.videos().insert(
    part=','.join(body.keys()),
    body=body,
    media_body=googleapiclient.http.MediaFileUpload(
      filename, chunksize=UPLOAD_CHUNK_SIZE, resumable=True)
  )
  progress_filename = os.path.join(UPLOADS_DIR, '%s.json' % os.path.split(
    filename)[1])
  try:
    with open(progress_filename) as f:
      progress = json.load(f)
  except IOError:
    progress = None
  if progress is not None:
    logging.debug('Resuming existing upload from %s...', progress_filename)
    request.resumable_progress = progress['resumable_progress']
    request.resumable_uri = progress['resumable_uri']
  response = None
  try:
    _prev_percent = 0
    while response is None:
      status, response = request.next_chunk(num_retries=3)
      if status:
        with open(progress_filename, 'w') as f:
          json.dump({
            'resumable_progress': request.resumable_progress,
            'resumable_uri': request.resumable_uri}, f)
        _percent = status.progress()
        if _percent - _prev_percent > 0.01:
          logging.debug('Uploading at [%s]', '{:.2%}'.format(_percent))
          _prev_percent = _percent
  except httplib2.ServerNotFoundError:
    logging.debug('Couldn\'t upload %s since no connection is available.')
  else:
    logging.debug('Successfully uploaded %s', response)
    os.remove(filename)
    try:
      os.remove(progress_filename)
    except OSError:
      pass


def watch():
  """Background watcher which removes old videos and tries to perform an upload.
  """
  while True:
    while not enough_disk_space():
      make_room()
    for i in reversed([i for i, p in enumerate(queue) if not p.is_alive()]):
      queue.pop(i)
    if queue:
      logging.debug('Upload queue: %s', queue)

    if is_connected():
      for video in sorted(os.listdir(VIDEO_DIR)):
        filename = os.path.join(VIDEO_DIR, video)
        if filename in [i.name for i in queue]:
          continue
        if os.stat(filename).st_size < MIN_VIDEO_SIZE:
          continue
        if len(queue) < UPLOAD_MAX_WORKERS:
          p = multiprocessing.Process(target=upload, name=filename, args=[filename])
          logging.debug('Starting background process %s', p)
          p.start()
          queue.append(p)
    time.sleep(SPACE_CHECK_INTERVAL)


class OutputShard(object):
  def __init__(self, filename):
    self.filename = filename
    self.is_new = self.size == 0
    self.stream = open(filename, 'ab')

  def __repr__(self):
    return '<OutputShard:%s>' % self.filename

  def write(self, buf):
    self.stream.write(buf)

  def close(self):
    self.stream.close()

  def remove(self):
    os.remove(self.filename)

  @property
  def size(self):
    try:
      return os.stat(self.filename).st_size
    except OSError:
      return 0


def record():
  """Start recording if/after no connection is avilable and stop when connected.

  The idea is to stop recording so the upload can be completed without
  generating any new videos, and you are very unlikely to need a recordding when
  you are near WiFi anyway.
  """
  with picamera.PiCamera() as camera:
    # make sure that camera is connected
    pass
  while is_connected():
    logging.debug('Still connected to the network...')
    time.sleep(5)

  now = datetime.datetime.now()
  # guard against writing into old files if system time is incorrect
  old_videos = [datetime.datetime.strptime(
    i.split('.')[0], DATE_FORMAT) for i in sorted(os.listdir(VIDEO_DIR))]
  for old_video in old_videos:
    if old_video >= now:
      shards = len([i for i in old_videos if i == old_video])
      if shards > 1:
        logging.critical('Existing video file %s is newer from current time %s. This is likely caused by incorrent system time. Trying again shortly...', old_video, now)
        time.sleep(10)
        return record()

  with picamera.PiCamera() as camera:
    camera.resolution = RESOLUTION
    camera.framerate = FRAMERATE
    camera.video_stabilization = STABILIZATION
    logging.debug('Recording with %s@%s FPS', RESOLUTION, FRAMERATE)
    camera.annotate_background = picamera.Color('black')
    counter = 0
    timestamp = now.strftime(DATE_FORMAT)
    filename = os.path.join(VIDEO_DIR, '%s.{}.%s' % (timestamp, FORMAT))
    shard = OutputShard(filename.format(str(counter).zfill(ZFILL_DECIMAL)))
    is_new = shard.is_new
    camera.start_recording(shard, format=FORMAT, intra_period=INTERVAL * FRAMERATE)
    intervals_recorded = 0
    while True:
      camera.annotate_text = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
      camera.split_recording(shard)
      camera.wait_recording(INTERVAL)
      intervals_recorded += 1
      if intervals_recorded % 10 == 0:
        logging.debug('Recorded %s intervals...', intervals_recorded)
      if shard.size > MAX_VIDEO_SIZE:
        counter += 1
        logging.debug('Using next shard %s for video file', counter)
      if is_connected():
        logging.info('Connected to WiFi. Not recording anymore.')
        camera.stop_recording()
        shard.close()
        if is_new and intervals_recorded < VIDEO_MIN_INTERVALS:
          logging.debug('Cleaning up short video %s (%s intervals)', shard, intervals_recorded)
          shard.remove()
        break
      shard = OutputShard(filename.format(str(counter).zfill(ZFILL_DECIMAL)))
  logging.info('Trying to start recording again...')
  record()


def main():
  logging.info('Powered on at %s', datetime.datetime.now())
  if not os.path.isdir(VIDEO_DIR):
    logging.debug('Creating directory %s', VIDEO_DIR)
    os.mkdir(VIDEO_DIR)
  if not os.path.isdir(UPLOADS_DIR):
    logging.debug('Creating directory %s', UPLOADS_DIR)
    os.mkdir(UPLOADS_DIR)
  p = multiprocessing.Process(target=watch, name='watcher')
  logging.debug('Starting background process %s', p)
  p.start()
  record()


if __name__ == '__main__':
  try:
    main()
  except KeyboardInterrupt:
    exit('Command killed by keyboard interrupt')
  except Exception as e:
    logging.exception(e)
