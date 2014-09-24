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

	def __init__(self, dev):
		self.dev = dev
		self.fd = open(dev, 'rb')
		self.value_struct = struct.Struct('I')

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
		v, = self.value_struct.unpack(readval)
		return v & self.PULSE_BIT != 0, v & self.PULSE_MASK


def read_byte(dev, bits=8):
	"""Reads a single byte from the IR transmission."""

	margin = 100	# acceptable margin of error
	byte = 0
	i = 0

	while i < bits:
		is_pulse, pulse_len = dev.read()

		# wait for pulse
		if not is_pulse and i == 0:
			continue

		v = -1
		if is_pulse and 500-margin < pulse_len < 500+margin:
			is_pulse, pulse_len = dev.read()
			if not is_pulse:
				if 500-margin < pulse_len < 500+margin:
					v = 1
				elif 1000-margin < pulse_len < 1000+margin:
					v = 0

		# reset bit counter if we didn't see a full byte
		if v == -1:
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


def record_weight(credentials, doc_key, weight):
	try:
		timestamp = datetime.now()

		gspread_creds = gspread.authorize(credentials)
		sheet = gspread_creds.open_by_key(doc_key).sheet1
		sheet.append_row((timestamp, weight))

		print('recorded', timestamp, weight)
	except HTTPError as e:
		print('error updating Google spreadsheet', e.response.status, e.response.reason)


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('--test', action='store_true', help='Tests authentication and logging')
	ap.add_argument('--debug', action='store_true', help='Displays debugging info')
	ap.add_argument('--dev', default='/dev/lirc0', help='LIRC device (default: "%(default)s")')
	ap.add_argument('--tokenfile', default=datafile('gdocs.token'), 
		help='File which stores the access_token (default: "%(default)s")')
	ap.add_argument('spreadsheet_key', help='Spreadsheet "key"')
	args = ap.parse_args()

	credentials = get_authorization(args.tokenfile)

	if args.test:
		record_weight(credentials, args.spreadsheet_key, 0.0)
		sys.exit(0)

	# main loop

	dev = lirc(args.dev)
	data = []
	stable = 0

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

				if args.debug:
					print('%02x' % data[1], weight)

				if data[1] == 0x8C:
					stable += 1
				else:
					stable = 0
			except:
				print('checksum failed')
			finally:
				data = []

			# record the weight if it is valid and stable
			if weight > 0 and stable >= 5:
				record_weight(credentials, args.spreadsheet_key, weight)
				stable = -10


if __name__ == '__main__':
	main()

