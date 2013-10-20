import datetime
from distutils.version import StrictVersion
import fcntl
import os
import pty
from seesaw import item
import seesaw
from seesaw.config import NumberConfigValue, realize
from seesaw.externalprocess import WgetDownload
from seesaw.item import ItemInterpolation, ItemValue
from seesaw.pipeline import Pipeline
from seesaw.project import Project
from seesaw.task import SimpleTask, LimitConcurrent, ConditionalTask, Task
from seesaw.tracker import (GetItemFromTracker, SendDoneToTracker,
	PrepareStatsForTracker, UploadWithTracker, TrackerRequest, RsyncUpload,
	CurlUpload)
from seesaw.util import find_executable
import shutil
import subprocess
import time
from tornado.ioloop import IOLoop, PeriodicCallback
import random, string, sys, functools, json, re

# check the seesaw version before importing any other components
if StrictVersion(seesaw.__version__) < StrictVersion("0.0.15"):
	raise Exception("This pipeline needs seesaw version 0.0.15 or higher.")


# # Begin AsyncPopen fix
class AsyncPopenFixed(seesaw.externalprocess.AsyncPopen):
	"""
	Start the wait_callback after setting self.pipe, to prevent an infinite
	spew of "AttributeError: 'AsyncPopen' object has no attribute 'pipe'"
	"""
	def run(self):
		self.ioloop = IOLoop.instance()
		(master_fd, slave_fd) = pty.openpty()

		# make stdout, stderr non-blocking
		fcntl.fcntl(master_fd, fcntl.F_SETFL,
			fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

		self.master_fd = master_fd
		self.master = os.fdopen(master_fd)

		# listen to stdout, stderr
		self.ioloop.add_handler(master_fd, self._handle_subprocess_stdout,
			self.ioloop.READ)

		slave = os.fdopen(slave_fd)
		self.kwargs["stdout"] = slave
		self.kwargs["stderr"] = slave
		self.kwargs["close_fds"] = True
		self.pipe = subprocess.Popen(*self.args, **self.kwargs)

		self.stdin = self.pipe.stdin

		# check for process exit
		self.wait_callback = PeriodicCallback(self._wait_for_end, 250)
		self.wait_callback.start()

seesaw.externalprocess.AsyncPopen = AsyncPopenFixed
# # End AsyncPopen fix


class DualWriter(object):
	def __init__(self, alt, filename, mode="a"):
		print "Opening %s..." % filename
		self.f = open(filename, mode)
		self.alt = alt
		
	def write(self, data):
		self.f.write(data)
		for output in self.alt:
			output(data)
		
	def close(self):
		self.f.close()
		
class RangeInterpolation(object):
	def __init__(self, *s):
		self.s = s

	def realize(self, item):
		return_list = []
		for id_ in xrange(item["start_id"], item["end_id"] + 1):
			for x in self.s:
				torrent_base, warc_base = item["file_bases"][id_]
				item["range_filename"] = torrent_base
				return_list.append(x % item)
				item["range_filename"] = warc_base
				return_list.append(x % item)
		return return_list
		
	def __str__(self):
		return "<'" + self.s + "'>"

###########################################################################
# Find a useful Wget+Lua executable.
#
# WGET_LUA will be set to the first path that
# 1. does not crash with --version, and
# 2. prints the required version string
WGET_LUA = find_executable(
	"Wget+Lua",
	["GNU Wget 1.14.lua.20130523-9a5c"],
	[
		"./wget-lua",
		"./wget-lua-warrior",
		"./wget-lua-local",
		"../wget-lua",
		"../../wget-lua",
		"/home/warrior/wget-lua",
		"/usr/bin/wget-lua"
	]
)

if not WGET_LUA:
	raise Exception("No usable Wget+Lua found.")


###########################################################################
# The version number of this pipeline definition.
#
# Update this each time you make a non-cosmetic change.
# It will be added to the WARC files and reported to the tracker.
VERSION = "20131018.01"
USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:24.0) Gecko/20100101 Firefox/24.0"
TRACKER_ID = 'isoprey'
TRACKER_HOST = 'tracker.archiveteam.org'


###########################################################################
# This section defines project-specific tasks.
#
# Simple tasks (tasks that do not need any concurrency) are based on the
# SimpleTask class and have a process(item) method that is called for
# each item.
class PrepareDirectories(SimpleTask):
	def __init__(self, file_prefix):
		SimpleTask.__init__(self, "PrepareDirectories")
		self.file_prefix = file_prefix

	def process(self, item):
		item_name = item["item_name"]
		
		assert "-" in item_name
		start, end = [int(x) for x in item_name.split("-", 1)]
		
		item["start_id"] = start
		item["end_id"] = end
		item["file_bases"] = {}
		
		dirname = "/".join((item["data_dir"], item_name))
		
		if os.path.isdir(dirname):
			shutil.rmtree(dirname)
			
		item.log_output("Creating directory %s" % dirname)
		os.makedirs(dirname)
		
		item["item_dir"] = dirname
		
		for id_ in xrange(start, end + 1):
			file_base = "%s-%s-%s" % (self.file_prefix, time.strftime("%Y%m%d-%H%M%S"), id_,)
			torrent_base = "%s.torrent" % file_base
			warc_base = "%s.warc.gz" % file_base
			item["file_bases"][id_] = (torrent_base, warc_base)
			item.log_output("Creating file %s" % "%s/%s" % (dirname, torrent_base))
			open("%s/%s" % (dirname, torrent_base), "w").close()
			item.log_output("Creating file %s" % "%s/%s" % (dirname, warc_base))
			open("%s/%s" % (dirname, warc_base), "w").close()

class WgetDownloadTorrentRange(Task):
	def __init__(self, args, retry_delay=30, max_tries=1, accept_on_exit_code=[0], retry_on_exit_code=None, env=None, stdin_data_function=None):
		Task.__init__(self, "WgetDownloadTorrentRange")
		self.args = args
		self.max_tries = max_tries
		self.accept_on_exit_code = accept_on_exit_code
		self.retry_on_exit_code = retry_on_exit_code
		self.env = env
		self.stdin_data_function = stdin_data_function
		self.retry_delay = retry_delay
		
	def enqueue(self, item):
		self.start_item(item)
		item["current_is_torrent"] = True
		item["tries"] = 0
		item["torrent_404"] = False
		self.process(item)
		
	def process(self, item):
		item["current_id"] = item["start_id"] - 1
		self.set_next_url(item)
		self.process_one(item)
		
	def set_next_url(self, item):
		try:
			item["logwriter"].close()
		except KeyError, e:
			pass
			
		if item["current_is_torrent"]:			
			if item["current_id"] < item["end_id"]:
				item["current_id"] += 1
				item["current_url"] = "http://ca.isohunt.com/download/%d/%s.torrent" % (item["current_id"], "".join(random.choice(string.letters + string.digits + '-') for x in xrange(0,random.randint(6, 16))))
				#item["logwriter"] = DualWriter([sys.stdout.write, item.log_output], "%s/torrent-%d.log" % (item["item_dir"], item["current_id"]))
				#item["logwriter"] = DualWriter([item.log_output], "%s/torrent-%d.log" % (item["item_dir"], item["current_id"]))
				item["logwriter"] = DualWriter([], "%s/torrent-%d.log" % (item["item_dir"], item["current_id"]))
				return True
			else:
				return False
		else:
			item["current_url"] = "http://ca.isohunt.com/torrent_details/%d/" % item["current_id"]
			#item["logwriter"] = DualWriter([item.log_output], "%s/details-%d.log" % (item["item_dir"], item["current_id"]))
			item["logwriter"] = DualWriter([], "%s/details-%d.log" % (item["item_dir"], item["current_id"]))
			return True
		
	def process_one(self, item):
		with self.task_cwd():
			url = item["current_url"]
			torrent_name, warc_name = item["file_bases"][item["current_id"]]
			
			if item["current_is_torrent"]:
				extra_args = ["-O", "%s/%s" % (item["item_dir"], torrent_name)]
			else:
				extra_args = ["--page-requisites", "-r", "-np", "-P", item["item_dir"], "--warc-file", "%s/%s" % (item["item_dir"], warc_name.replace(".warc.gz", ""))]
				
			item.log_output("Start downloading URL %s" % url)

			p = seesaw.externalprocess.AsyncPopen(
				args=realize(self.args, item) + extra_args + [url],
				env=realize(self.env, item),
				stdin=subprocess.PIPE,
				close_fds=True
			)

			p.on_output += functools.partial(self.on_subprocess_stdout, p, item)
			p.on_end += functools.partial(self.on_subprocess_end, item)

			p.run()

			p.stdin.write(self.stdin_data(item))
			p.stdin.close()
		
	def handle_done(self, item):
		item.log_output("Finished %s for %s\n" % (self, item.description()))
		item["logwriter"].close()
		self.complete_item(item)
		
	def handle_process_result(self, exit_code, item):
		if item["current_is_torrent"]:
			item.log_output("Found torrent for ID %s, fetching metadata..." % item["current_id"])
		else:
			item.log_output("Metadata for ID %s fetched. Moving on to next ID..." % item["current_id"])
		item["current_is_torrent"] = not item["current_is_torrent"]
		if self.set_next_url(item):
			self.process_one(item)
		else:
			self.handle_done(item)
			
	def stdin_data(self, item):
		if self.stdin_data_function:
			return self.stdin_data_function(item)
		else:
			return ""
			
	def on_subprocess_stdout(self, pipe, item, data):
		try:
			item["logwriter"].write(data)
		except ValueError, e:
			pass # Not sure why this happens, but it breaks shit
		
		if item["current_is_torrent"] and "ERROR 404: Not Found" in data:
			item["torrent_404"] = True
		#item.log_output(data, full_line=False)

	def on_subprocess_end(self, item, returncode):
		if returncode in self.accept_on_exit_code:
			self.handle_process_result(returncode, item)
		else:
			self.handle_process_error(returncode, item)

	def handle_process_error(self, exit_code, item):
		if item["current_is_torrent"] == True:
			# Torrent doesn't exist, so there's no point in trying to download other pages
			if item["torrent_404"]:
				item.log_output("404 for torrent file detected, skipping ID %s..." % item["current_id"])
				if self.set_next_url(item):
					self.process_one(item)
				else:
					self.handle_done(item)
				return
			else:
				item.log_output("Got throttled on ID %s, waiting 1200 seconds before retry..." % item["current_id"])
				retry_delay = 1200
				# fall through to retry
		else:
			retry_delay = self.retry_delay
		
		item["tries"] += 1

		item.log_output("Process %s returned exit code %d for %s\n" % (self, exit_code, item.description()))
		item.log_error(self, exit_code)

		if (self.max_tries == None or item["tries"] < self.max_tries) and (self.retry_on_exit_code == None or exit_code in self.retry_on_exit_code):
			item.log_output("Retrying %s for %s after %d seconds...\n" % (self, item.description(), self.retry_delay))
			IOLoop.instance().add_timeout(datetime.timedelta(seconds=self.retry_delay),
				functools.partial(self.process_one, item))
		else:
			item.log_output("Failed %s for %s\n" % (self, item.description()))
			item["logwriter"].close()
			self.fail_item(item)


class MoveFiles(SimpleTask):
	def __init__(self):
		SimpleTask.__init__(self, "MoveFiles")

	def process(self, item):
		for id_ in xrange(item["start_id"], item["end_id"] + 1):
			torrent_base, warc_base = item["file_bases"][id_]
			
			from_ = "%s/%s" % (item["item_dir"], torrent_base)
			to_ = "%s/%s" % (item["data_dir"], torrent_base)
			item.log_output("Moving file from %s to %s" % (from_, to_))
			os.rename(from_, to_)
			
			from_ = "%s/%s" % (item["item_dir"], warc_base)
			to_ = "%s/%s" % (item["data_dir"], warc_base)
			item.log_output("Moving file from %s to %s" % (from_, to_))
			os.rename(from_, to_)
			
		shutil.rmtree("%(item_dir)s" % item)

class CleanUpDirectories(SimpleTask):
	def __init__(self):
		SimpleTask.__init__(self, "CleanUpDirectories")
		
	def process(self, item):
		shutil.rmtree("%(item_dir)s" % item)

class PrepareStatsForTracker2(SimpleTask):
	'''Similar to PrepareStatsForTracker but calls realize on files earlier'''
	def __init__(self, defaults=None, file_groups=None, id_function=None):
		SimpleTask.__init__(self, "PrepareStatsForTracker2")
		self.defaults = defaults or {}
		self.file_groups = file_groups or {}
		self.id_function = id_function

	def process(self, item):
		total_bytes = {}
		for (group, files) in self.file_groups.iteritems():
			total_bytes[group] = sum([ os.path.getsize(f) for f in realize(files, item)])

		stats = {}
		stats.update(self.defaults)
		stats["item"] = item["item_name"]
		stats["bytes"] = total_bytes

		if self.id_function:
			stats["id"] = self.id_function(item)

		item["stats"] = realize(stats, item)
		
class UploadWithTracker2(TrackerRequest):
	'''Similar to UploadWithTracker but calls realize on files earlier'''
	def __init__(self, tracker_url, downloader, files, version=None, rsync_target_source_path="./", rsync_bwlimit="0", rsync_extra_args=[], curl_connect_timeout="60", curl_speed_limit="1", curl_speed_time="900"):
		TrackerRequest.__init__(self, "Upload2", tracker_url, "upload")

		self.downloader = downloader
		self.version = version

		self.files = files
		self.rsync_target_source_path = rsync_target_source_path
		self.rsync_bwlimit = rsync_bwlimit
		self.rsync_extra_args = rsync_extra_args
		self.curl_connect_timeout = curl_connect_timeout
		self.curl_speed_limit = curl_speed_limit
		self.curl_speed_time = curl_speed_time

	def data(self, item):
		data = {"downloader": realize(self.downloader, item),
				"item_name": item["item_name"]}
		if self.version:
			data["version"] = realize(self.version, item)
		return data

	def process_body(self, body, item):
		data = json.loads(body)
		if "upload_target" in data:
			files = realize(self.files, item)
			inner_task = None

			if re.match(r"^rsync://", data["upload_target"]):
				item.log_output("Uploading with Rsync to %s" % data["upload_target"])
				inner_task = RsyncUpload(data["upload_target"], files, target_source_path=self.rsync_target_source_path, bwlimit=self.rsync_bwlimit, extra_args=self.rsync_extra_args, max_tries=1)

			elif re.match(r"^https?://", data["upload_target"]):
				item.log_output("Uploading with Curl to %s" % data["upload_target"])

				if len(files) != 1:
					item.log_output("Curl expects to upload a single file.")
					self.fail_item(item)
					return

				inner_task = CurlUpload(data["upload_target"], files[0], self.curl_connect_timeout, self.curl_speed_limit, self.curl_speed_time, max_tries=1)

			else:
				item.log_output("Received invalid upload type.")
				self.fail_item(item)
				return

			inner_task.on_complete_item += self._inner_task_complete_item
			inner_task.on_fail_item += self._inner_task_fail_item
			inner_task.enqueue(item)

		else:
			item.log_output("Tracker did not provide an upload target.")
			self.schedule_retry(item)

	def _inner_task_complete_item(self, task, item):
		self.complete_item(item)

	def _inner_task_fail_item(self, task, item):
		self.schedule_retry(item)

###########################################################################
# Initialize the project.
#
# This will be shown in the warrior management panel. The logo should not
# be too big. The deadline is optional.
project = Project(
	title="Isohunt",
	project_html="""
	<img class="project-logo" alt="" src="http://cryto.net/~joepie91/isohunt_logo.png" height="50"/>
	<h2>Isohunt <span class="links"><a href="http://isohunt.com/">Website</a> &middot; <a href="http://%s/%s/">Leaderboard</a></span></h2>
	<p>Archiving torrents and metadata from <b>Isohunt</b></p>
	""" % (TRACKER_HOST, TRACKER_ID)
	, utc_deadline=datetime.datetime(2013, 10, 24, 00, 00, 1)
)

""" Old stuff
WgetDownload([
		WGET_LUA,
		"-U", USER_AGENT,
		#"-o", ItemInterpolation("%(item_dir)s/wget.log"),  #TODO: Multiple logs?
		"--no-check-certificate",
		"--output-document", ItemInterpolation("%(item_dir)s/%(file_base)s"),
		"-e", "robots=off",
		"--rotate-dns",
		"--timeout", "60",
		"--level=inf",
		"--tries", "20",
		"--waitretry", "5"
		],
		max_tries=5,
		accept_on_exit_code=[ 0 ],
	),"""

pipeline = Pipeline(
	GetItemFromTracker("http://%s/%s" % (TRACKER_HOST, TRACKER_ID), downloader,
		VERSION),
	PrepareDirectories(file_prefix="isohunt"),
	LimitConcurrent(NumberConfigValue(min=1, max=6, default="6",
		name="isohunt:download_threads", title="Isohunt downloading threads",
		description="How many threads downloading Isohunt torrents and pages can run at once, to avoid throttling."),
		WgetDownloadTorrentRange([
			WGET_LUA,
			"-U", USER_AGENT,
      "--bind-address", "x.x.x.x",
			"--no-check-certificate",
			"-e", "robots=off",
			"--rotate-dns",
			"--timeout", "60",
			"--level=inf",
			"--tries", "20",
			"--waitretry", "5"
			],
			max_tries=5,
			accept_on_exit_code=[ 0 ]
		),
	),
	PrepareStatsForTracker2(
		defaults={ "downloader": downloader, "version": VERSION },
		file_groups={
			"data": RangeInterpolation("%(item_dir)s/%(range_filename)s")
			}
	), # Used to MoveFiles here, but that's actually kind of stupid.
	LimitConcurrent(NumberConfigValue(min=1, max=4, default="1",
		name="shared:rsync_threads", title="Rsync threads",
		description="The maximum number of concurrent uploads."),
		UploadWithTracker2(
			"http://tracker.archiveteam.org/%s" % TRACKER_ID,
			downloader=downloader,
			version=VERSION,
			files=RangeInterpolation("%(item_dir)s/%(range_filename)s"),
			rsync_target_source_path=ItemInterpolation("%(data_dir)s/"),
			rsync_extra_args=[
				"--recursive",
				"--partial",
				"--partial-dir", ".rsync-tmp"
			]
			),
	),
	CleanUpDirectories(),
	SendDoneToTracker(
		tracker_url="http://%s/%s" % (TRACKER_HOST, TRACKER_ID),
		stats=ItemValue("stats")
	)
)
