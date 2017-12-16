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


VIDEODIR = os.path.join(os.path.dirname(__file__), 'video')
FILETYPE = 'h264'

# how many 0s to put in front of counter number
# will start to screw up when video has passed (INTERVAL)*10^(ZFILL_DECIMAL) seconds in length
ZFILL_DECIMAL = 6

# best settings for 5mp V1 camera
# (pixel width, height)
# RESOLUTION = (1296, 972)
# FRAMERATE = 30

# 8mp V2 camera
RESOLUTION = (1640, 1232)
FRAMERATE = 30

# number of seconds to film each video
INTERVAL = 5

# check for enough disk space every (this many) of above intervals
SPACE_CHECK_INTERVAL = 100

# what % of disk space must be free to start a new video
REQUIRED_FREE_SPACE_PERCENT = 15  # about an hour with 64gb card


def make_room(videodir):
  """Clear oldest video.
  """
  sorted_videos = sorted(os.listdir(videodir))
  if sorted_videos:
    oldest_video = sorted_videos[0]
    logging.dedbug('Removing oldest video: %s', oldest_video)
    # may not have permission if running as pi and video was created by root
    try:
      shutil.rmtree('{}/{}'.format(videodir, oldest_video))
    except OSError:
      logging.error('Must run as root otherwise script cannot clear out old videos')
      exit(1)
  else:
    logging.debug('No videos in directory %s, cannot make room', videodir)


def enough_disk_space(required_free_space_percent):
  """Return true if we have enough space to start a new video.
  """
  df = subprocess.Popen(['df', '/'], stdout=subprocess.PIPE)
  output = df.communicate()[0]
  percent_used_str = output.split("\n")[1].split()[4]
  percent_used = int(percent_used_str.replace('%', ''))
  logging.debug('%s%% of disk space used.', percent_used)
  enough = 100 >= required_free_space_percent + percent_used
  logging.debug('Enough space to start new video: %s', enough)
  return enough


def generate_filename(videodir, timestamp, counter, filetype):
  """Going to look like: 2017-03-08-09-54-27.334326-000001.h264.
  """
  filename_prefix = '{}/{}'.format(videodir, timestamp)
  if not os.path.isdir(filename_prefix):
    logging.debug('Creating directory %s', filename_prefix)
    os.makedirs(filename_prefix)
  zfill_counter = str(counter).zfill(ZFILL_DECIMAL)
  filename = '{}/{}-{}.{}'.format(filename_prefix, timestamp, zfill_counter, filetype)
  logging.debug('Recording %s', filename)
  return filename


def continuous_record(camera, videodir, timestamp, filetype, interval):
  """Record <interval> second files with prefix.
  """
  counter = 0
  initial_filename = generate_filename(videodir, timestamp, counter, filetype)
  camera.start_recording(initial_filename, intra_period=interval * FRAMERATE)
  while True:
    counter += 1
    split_filename = generate_filename(videodir, timestamp, counter, filetype)
    camera.split_recording(split_filename)
    camera.wait_recording(interval)
    if counter % SPACE_CHECK_INTERVAL == 0:
      while not enough_disk_space(REQUIRED_FREE_SPACE_PERCENT):
        make_room(videodir)
  camera.stop_recording()


def main():
  with picamera.PiCamera() as camera:
    # Initialization
    camera.resolution = RESOLUTION
    camera.framerate = FRAMERATE
    timestamp = str(datetime.datetime.now()).replace(' ', '-').replace(':', '-')
    while not enough_disk_space(REQUIRED_FREE_SPACE_PERCENT):
      make_room(VIDEODIR)

    # start recording, chunking files every <interval> seconds
    continuous_record(camera, VIDEODIR, timestamp, FILETYPE, INTERVAL)


if __name__ == '__main__':
  if len(sys.argv) > 1:
    if sys.argv[1] == '-d' or sys.argv[1] == '--debug':
      logging.basicConfig(level=logging.DEBUG)
  main()
