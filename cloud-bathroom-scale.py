#!/usr/bin/env python 
#
# Cloud-enabled bathroom scale
# -----------------------------
# Monitors an LIRC device for bathroom scale measurements and logs stable
# values to a Google Docs spreadsheet
#
# 2014.09.21 darell tan
#

import os
import sys
import argparse
from datetime import datetime
from time import time, sleep
from threading import Thread, Lock

from fcntl import ioctl
import struct, array

import gspread
from gspread.urls import SPREADSHEETS_FEED_URL
from gspread.httpsession import HTTPError
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage


class lirc:
	_IOW = lambda grp, nr, sz: 1 << 30 | sz << 16 | ord(grp) << 8 | nr
	_IOR = lambda grp, nr, sz: 2 << 30 | sz << 16 | ord(grp) << 8 | nr

	LIRC_GET_FEATURES = _IOR('i', 0x00, 4)
	LIRC_GET_REC_MODE = _IOR('i', 0x02, 4)
	LIRC_SET_REC_MODE = _IOW('i', 0x12, 4)

	LIRC_MODE_RAW      = 0x1
	LIRC_MODE_PULSE    = 0x2
	LIRC_MODE_MODE2    = 0x4
	LIRC_MODE_LIRCCODE = 0x8

	LIRC_CAN_REC_RAW      = LIRC_MODE_RAW      << 16
	LIRC_CAN_REC_PULSE    = LIRC_MODE_PULSE    << 16
	LIRC_CAN_REC_MODE2    = LIRC_MODE_MODE2    << 16
	LIRC_CAN_REC_LIRCCODE = LIRC_MODE_LIRCCODE << 16

	PULSE_BIT  = 0x01000000
	PULSE_MASK = 0x00FFFFFF

	DEBUG_LOG = None

	def __init__(self, dev):
		self.dev = dev
		self.fd = open(dev, 'rb')
		self.value_struct = struct.Struct('I')

		# for debug logging
		self.debug_fd = None
		if self.DEBUG_LOG is not None:
			self.debug_fd = open(self.DEBUG_LOG, 'wb')

	def ioctl(self, req):
		buf = array.array('I', [0])
		r = ioctl(self.fd, req, buf, 1)
		return r, buf[0]

	def get_features(self):
		r, val = self.ioctl(self.LIRC_GET_FEATURES)
		return val if r == 0 else None

	def get_rec_mode(self):
		r, val = self.ioctl(self.LIRC_GET_REC_MODE)
		return val if r == 0 else None

	def read(self):
		readval = self.fd.read(self.value_struct.size)
		if self.debug_fd:
			self.debug_fd.write(readval)
		v, = self.value_struct.unpack(readval)
		return v & self.PULSE_BIT != 0, v & self.PULSE_MASK


class gpioled:
	def __init__(self, pin):
		self.path = '/sys/class/gpio/gpio%d/value' % pin

		self.fd = None
		if not os.path.exists(self.path):
			raise ValueError('GPIO pin %d has not been exported' % pin)
		elif not os.access(self.path, os.W_OK):
			raise ValueError('cannot control GPIO pin %d - check permissions' % pin)

		self.fd = open(self.path, 'wb', 0)
		self.state = True	# initial state

	def __del__(self):
		if self.fd is not None:
			self.set_state(False)
			self.fd.close()

	def set_state(self, state):
		self.state = bool(state)
		self.fd.write('1' if self.state else '0')

	def toggle(self):
		self.set_state(self.state)
		self.state = not self.state


class weight_state:
	def __init__(self):
		self.update_lock = Lock()

		self.stable_count = 0
		self.last_stable_time = 0
		self.stable_weight = 0

		self.last_update_time = 0
		self.weight = 0

	def update(self, is_stable, weight):
		now = time()
		if is_stable:
			self.stable_count += 1
			self.last_stable_time = now
			self.stable_weight = weight
		else:
			self.stable_count = 0

		self.last_update_time = now
		self.weight = weight

	def can_record(self):
		now = time()
		return self.stable_count >= 10 and \
			self.stable_weight > 0 and \
			now - self.last_stable_time > 2


def read_byte(dev, bits=8):
	"""Reads a single byte from the IR transmission."""

	margin = 200	# acceptable margin of error
	margin2 = 15000
	byte = 0
	i = 0
	durations = []

	while i < bits:
		is_pulse, pulse_len = dev.read()
		durations.extend([is_pulse, pulse_len])

		# wait for pulse
		if not is_pulse and i == 0:
			continue

		v = -1
		if is_pulse and 500-margin < pulse_len < 500+margin:
			is_pulse, pulse_len = dev.read()
			durations.extend([is_pulse, pulse_len])
			if not is_pulse:
				if 500-margin < pulse_len < 500+margin:
					v = 1
				elif 1000-margin < pulse_len < 1000+margin:
					v = 0
				elif 75000-margin2 < pulse_len < 75000+margin2 and i == 0:
					continue

		# reset bit counter if we didn't see a full byte
		if v == -1:
			#print(repr(durations))
			i = 0
			return None

		byte |= v << (7 - i)
		i += 1

	return byte


def verify_checksum(data):
	checksum = 0
	for n in data[:4]:
		checksum += n
		checksum %= 0xff
	checksum &= ~1
	assert checksum == data[4]


def datafile(fname):
	return os.path.join(os.path.dirname(__file__), fname)


def get_authorization(cache_file):
	"""Requests for authorization if necessary, otherwise uses the 
	cached token."""

	store = Storage(cache_file)
	credentials = store.get()
	if credentials is None:

		flow = flow_from_clientsecrets(datafile('client_secrets.json'),
								   scope=SPREADSHEETS_FEED_URL,
								   redirect_uri='oob')

		auth_uri = flow.step1_get_authorize_url()
		print('1. Visit the following URL to grant access:\n%s\n' % auth_uri)
		print('2. Read the instructions on the website and click the "Accept" button')

		code = raw_input('3. Paste the code here: ')
		code = code.strip()

		credentials = flow.step2_exchange(code)
		credentials.set_store(store)
		store.put(credentials)

	return credentials


def record_weight(state, credentials, doc_key):
	try:
		timestamp = datetime.now()

		print('updating spreadsheet...')

		gspread_creds = gspread.authorize(credentials)
		sheet = gspread_creds.open_by_key(doc_key).sheet1
		sheet.append_row((timestamp, state.stable_weight))

		print('recorded', timestamp, state.stable_weight)
		return True
	except HTTPError as e:
		print('error updating Google spreadsheet', e.response.status, e.response.reason)
		return False
	finally:
		pass


def record_stable_weight(state, led, credentials, doc_key):
	try:
		while True:
			if state.can_record():
				led.set_state(True)
				record_weight(state, credentials, doc_key)
				break

			sleep(0.5)
	finally:
		led.set_state(False)
		state.update_lock.release()


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('--test', action='store_true', help='Tests authentication and logging')
	ap.add_argument('--debug', action='store_true', help='Displays debugging info')
	ap.add_argument('--dev', default='/dev/lirc0', help='LIRC device (default: "%(default)s")')
	ap.add_argument('--led', type=int, default=18, help='GPIO pin for status LED (default: "%(default)s")')
	ap.add_argument('--tokenfile', default=datafile('gdocs.token'), 
		help='File which stores the access_token (default: "%(default)s")')
	ap.add_argument('spreadsheet_key', help='Spreadsheet "key"')
	args = ap.parse_args()

	credentials = get_authorization(args.tokenfile)

	if args.test:
		state = weight_state()
		record_weight(state, credentials, args.spreadsheet_key)
		sys.exit(0)

	# main loop

	led = gpioled(args.led)
	dev = lirc(args.dev)
	state = weight_state()
	data = []

	print('monitoring LIRC device...')

	while True:
		num_bits = 8 if len(data) < 4 else 7
		b = read_byte(dev, num_bits)
		if b is None or (data and data[0] != 0xAB):
			data = []
			continue

		data.append(b)

		if len(data) == 5:
			weight = -1
			try:
				if args.debug:
					print(['%02x' % d for d in data])

				verify_checksum(data)
				weight = data[2] << 8 | data[3]
				weight /= 10.0

				led.toggle()

				if args.debug:
					print('%02x' % data[1], weight)

				state.update(data[1] == 0x8C, weight)
			except:
				print('checksum failed')
			finally:
				data = []

			# start process to monitor for stable weight and record it
			if state.stable_count > 10 and state.update_lock.acquire(False):
				p = Thread(target=record_stable_weight, 
						args=(state, led, credentials, args.spreadsheet_key))
				p.start()


if __name__ == '__main__':
	main()

