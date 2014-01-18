#!/usr/bin/env python2

# Copyright 2014 Igor Gnatenko
# Author(s): Igor Gnatenko <i.gnatenko.brain AT gmail DOT com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
# See http://www.gnu.org/copyleft/gpl.html for the full text of the license.

import os
import sys
import ConfigParser
import argparse
import urlgrabber
import urlgrabber.progress
import git
import re
import subprocess
import stat
import glob
import shutil
import signal

WORK_DIR = os.getcwd()

class Options:
  def __init__(self, work_dir):
    signal.signal(signal.SIGINT, self.handler_clean)
    try:
      self.repo = git.Repo(work_dir)
    except git.exc.InvalidGitRepositoryError:
      print "Wtf? This folder not contains valid git repository!"
      sys.exit(1)
    assert self.repo.bare == False
    self.repo.config_reader()
    self.name = "kernel"
    self.hcommit = self.repo.head.commit
    self.sha = self.hcommit.hexsha
    try:
      self.author = self.hcommit.author
      self.summary = self.hcommit.summary
    except LookupError:
      print "Please fix https://github.com/gitpython-developers/GitPython/pull/57 before!"
      sys.exit(1)
    self.prefix = None
    self.format = "tar.gz"
    self.patch = None
    self.directory = "sources"
    self.ver = [None, None, None, None, None]
    self.released = False
    self.released_candidate = False
    self.get_kernel_info()
    self.prefix = "linux-%s.%s" % (self.ver[0], self.ver[1] if self.released else (int(self.ver[1]) - 1))
    self.sources = ["config-arm64", "config-arm-generic", "config-armv7", "config-armv7-generic", \
                    "config-armv7-lpae", "config-debug", "config-generic", "config-i686-PAE", "config-no-extra", \
                    "config-nodebug", "config-powerpc32-generic", "config-powerpc32-smp", \
                    "config-powerpc64", "config-powerpc64p7", "config-powerpc-generic", "config-s390x", \
                    "config-x86-32-generic", "config-x86_64-generic", "config-x86-generic", \
                    "cpupower.config", "cpupower.service", "Makefile", "Makefile.config", "Makefile.release", \
                    "merge.pl", "mod-extra.list", "mod-extra.sh", "mod-sign.sh", "x509.genkey"]
    try:
      with open("%s/config-local" % self.directory, "r"):
        pass
    except IOError, e:
      if e.errno == 2:
        self.sources.append("config-local")
    self.execute = ["merge.pl", "mod-extra.sh", "mod-sign.sh"]

  def handler_clean(self, signum, frame):
    self.clean_tree(True)
    sys.exit(0)

  def handler_checkout_clean(self, signum, frame):
    self.repo.git.checkout(self.sha)
    self.handler_clean()

  def get_kernel_info(self):
    lines = []
    with open("Makefile", "r") as f:
      lines = [f.next() for x in xrange(5)]
    i = 0
    for line in lines:
      self.ver[i] = re.sub(r"^.* = (.*)\n$", r"\1", line)
      i += 1
    if "=" in self.ver[3]:
      self.ver[3] = None
      self.released = True
      if re.search("^Linus Torvalds$", str(self.author)) and \
         re.search("^Linux %s.%s$" % (self.ver[0], self.ver[1]), self.summary):
        self.released_candidate = True
    else:
      self.released = False
      if re.search("^Linus Torvalds$", str(self.author)) and \
         re.search("^Linux %s.%s%s$" % (self.ver[0], self.ver[1], self.ver[3]), self.summary):
        self.released_candidate = True

  def print_info(self):
    if self.released:
      if self.released_candidate:
        print "Version: %s.%s" % (self.ver[0], self.ver[1])
      else:
        print "Version: %s.%s+" % (self.ver[0], self.ver[1])
    else:
      if self.released_candidate:
        print "Version: %s.%s%s" % (self.ver[0], self.ver[1], self.ver[3])
      else:
        print "Version: %s.%s%s+" % (self.ver[0], self.ver[1], self.ver[3])
    print "Codename: %s" % self.ver[4]
    print "Commit:\n  Author: %s\n  Summary: %s" % (self.author, self.summary)

  def set_execute(self):
    for source in self.execute:
      src = "%s/%s" % (self.directory, source)
      st = os.stat(src)
      os.chmod(src, st.st_mode | stat.S_IEXEC)

  def download_file(self, file_name):
    pg = urlgrabber.progress.TextMeter()
    urlgrabber.urlgrab("http://pkgs.fedoraproject.org/cgit/kernel.git/plain/%s" % file_name, \
                       "sources/%s" % file_name, progress_obj=pg)

  def download_sources(self):
    for source in self.sources:
      self.download_file(source)

  def download_spec(self):
    self.download_file("%s.spec" % self.name)

  def download_files(self):
    self.download_spec()
    self.download_sources()
    self.set_execute()

  def make_patch(self):
    if not self.released:
      self.patchfile = "%s/patch-%s.%s%s" % (self.directory, self.ver[0], self.ver[1], self.ver[3])
      patch = open(self.patchfile, "w")
      p = subprocess.Popen("git diff v%s.%s v%s.%s%s" % (self.ver[0], (int(self.ver[1]) - 1), \
                                                         self.ver[0], self.ver[1], self.ver[3]), \
                                                         shell=True, universal_newlines=True, stdout=patch)
      p.wait()
      patch.flush()
      patch.close()
      subprocess.call(["xz", "-z", self.patchfile])
      if not self.released_candidate:
        self.patchfile = "%s/patch-%s.%s%s-git999" % (self.directory, self.ver[0], self.ver[1], self.ver[3])
        patch = open(self.patchfile, "w")
        p = subprocess.Popen("git diff v%s.%s%s %s" % (self.ver[0], self.ver[1], self.ver[3], self.sha), \
                                                       shell=True, universal_newlines=True, stdout=patch)
        p.wait()
        patch.flush()
        patch.close()
        subprocess.call(["xz", "-z", self.patchfile])
    elif not self.released_candidate:
      self.patchfile = "%s/patch-%s.%s-git999" % (self.directory, self.ver[0], self.ver[1])
      patch = open(self.patchfile, "w")
      p = subprocess.Popen("git diff v%s.%s %s" % (self.ver[0], self.ver[1], self.sha), \
                                                   shell=True, universal_newlines=True, stdout=patch)
      p.wait()
      patch.flush()
      patch.close()
      subprocess.call(["xz", "-z", self.patchfile])

  def archive(self):
    signal.signal(signal.SIGINT, self.handler_checkout_clean)
    if not self.released:
      self.repo.git.checkout("v%s.%s" % (self.ver[0], (int(self.ver[1]) - 1)))
    f = open("%s/%s.%s" % (self.directory, self.prefix, self.format), "w")
    self.repo.archive(f, prefix="%s/" % self.prefix, format=self.format)
    f.close()
    if not self.released:
      self.repo.git.checkout(self.sha)
    signal.signal(signal.SIGINT, self.handler_clean)

  def parse_spec(self, args):
    lines = []
    with open("%s/%s.spec" % (self.directory, self.name), "r") as f:
      lines = f.readlines()
    first = True
    patches = glob.glob("%s/*.patch" % self.directory)
    patches.sort()
    i = 0
    while i < len(patches):
      patches[i] = re.sub("%s/" % self.directory, "", patches[i])
      i += 1
    i = 0
    while i < len(lines):
      if re.search("^%changelog", lines[i]):
        try:
          while True:
            del lines[i]
        except IndexError:
          pass
      elif re.search("^%global released_kernel [01]", lines[i]):
        lines[i] = re.sub(r"[01]", "1" if self.released else "0", lines[i])
        i += 1
      elif re.search("^# % define buildid .local", lines[i]):
        lines[i] = re.sub("# % ", "%", lines[i])
        if args.buildid:
          lines[i] = re.sub("local", "%s.%s" % (self.sha[:8], args.buildid), lines[i])
        else:
          lines[i] = re.sub("local", "%s" % self.sha[:8], lines[i])
        i += 1
      elif re.search("^%define base_sublevel [0-9]+", lines[i]):
        lines[i] = re.sub(r"[0-9]+", self.ver[1] if self.released else (str(int(self.ver[1]) - 1)), lines[i])
        i += 1
      elif re.search("^%define stable_update [0-9]+", lines[i]):
        lines[i] = re.sub(r"[0-9]+", self.ver[2], lines[i])
        i += 1
      elif re.search("^%define rcrev [0-9]+", lines[i]):
        lines[i] = re.sub(r"[0-9]+", re.sub(r"[^0-9]", "", self.ver[3]) if not self.released else "0", lines[i])
        i += 1
      elif re.search("^%define gitrev [0-9]+", lines[i]):
        lines[i] = re.sub(r"[0-9]+", "999" if not self.released_candidate else "0", lines[i])
        i += 1
      elif re.search("^%global baserelease [0-9]+", lines[i]):
        lines[i] = re.sub(r"[0-9]+", "999" if self.released else "1", lines[i])
        i += 1
      elif re.search("^%define debugbuildsenabled [01]", lines[i]):
        lines[i] = re.sub(r"[01]", "1" if args.separate_debug else "0", lines[i])
        i += 1
      elif re.search("^%define rawhide_skip_docs [01]", lines[i]):
        lines[i] = re.sub(r"[01]", "1", lines[i])
        i += 1
      elif re.search("^%define with_vanilla ", lines[i]):
        lines[i] = re.sub(r"[01]}(.*) [01]", r"1}\1 0", lines[i])
        i += 1
      elif re.search("^%define with_debuginfo ", lines[i]):
        lines[i] = re.sub(r"[01]}(.*) [01]", r"1}\1 0", lines[i])
        i += 1
      elif re.search("^%define with_perf ", lines[i]):
        lines[i] = re.sub(r"[01]}(.*) [01]", r"1}\1 0", lines[i])
        i += 1
      elif re.search("^%define listnewconfig_fail [01]", lines[i]) and not args.chk_config:
        lines[i] = re.sub(r"[01]", "0", lines[i])
        i += 1
      elif re.search("^Source0: ", lines[i]):
        lines[i] = re.sub(r" .*$", " %s.%s" % (self.prefix, self.format), lines[i])
        i += 1
      elif re.search("^Source[0-9]+: perf-man.tar.gz", lines[i]):
        lines[i] = re.sub(r"^", "#", lines[i])
        i += 1
      elif re.search("^%if !%{nopatches}", lines[i]) and args.patches:
        i += 1
        if first:
          j = 100
          for patch in patches:
            lines.insert(i, "Patch%s: %s\n" % (str(j), patch))
            j += 1
            i += 1
          first = False
        else:
          for patch in patches:
            lines.insert(i, "ApplyPatch %s\n" % patch)
            i += 1
      elif re.search("^(Patch[0-9]+:|Apply(Optional|)Patch) ", lines[i]) and \
           (re.search("^Patch00: patch-3.%{upstream_sublevel}-rc%{rcrev}.xz", lines[i]) or \
            re.search("^Patch01: patch-3.%{upstream_sublevel}-rc%{rcrev}-git%{gitrev}.xz", lines[i]) or \
            re.search("^Patch00: patch-3.%{base_sublevel}-git%{gitrev}.xz", lines[i])) is None:
        lines[i] = re.sub(r"^", "#", lines[i])
        i += 1
      else:
        i += 1
    f = open("%s/%s.spec" % (self.directory, self.name), "w")
    for line in lines:
      f.write(line)
    f.close()

  def make_srpm(self):
    subprocess.call(["rpmbuild", "-bs", "%s/%s.spec" % (self.directory, self.name), \
                     "-D", "_specdir %s/" % self.directory, \
                     "-D", "_sourcedir %s/" % self.directory, \
                     "-D", "_srcrpmdir %s/" % self.directory])

  def clean_tree(self, first_clean):
    try:
      os.stat(self.directory)
      if not os.access(self.directory, os.W_OK):
        print "Wtf? I don't have access to \"%s/\" directory!" % self.directory
        sys.exit(1)
    except OSError, e:
      if e.errno == 2:
        os.makedirs(self.directory)
    clean = glob.glob("%s/*" % self.directory)
    i = 0
    while i < len(clean):
      if re.search(".patch$", clean[i]) or \
         re.search("config-local$", clean[i]):
        del clean[i]
      elif re.search(".src.rpm$", clean[i]) and \
           not first_clean:
        del clean[i]
      else:
        i += 1
    for to_clean in clean:
      try:
        os.remove(to_clean)
      except OSError, e:
        if e.errno == 21 or e.errno == 39:
          shutil.rmtree(to_clean)

class Parser(argparse.ArgumentParser):
  def error(self, message):
    sys.stderr.write("error: %s\n" % message)
    self.print_help()
    sys.exit(2)

def set_args(parser):
  parser.add_argument("--buildid", dest="buildid", action="store", \
                      help="user build-id")
  parser.add_argument("--check-configs", dest="chk_config", action="store_true", \
                      help="enable check for new CONFIG options")
  parser.add_argument("--separate-debug", dest="separate_debug", action="store_true", \
                      help="separate debug kernel and main kernel")
  parser.add_argument("--without-patches", dest="patches", action="store_false", \
                      help="build kernel w/o/ patches")

def main():
  parser = Parser(description="Make RPM from upstream linux kernel easy.")
  set_args(parser)
  args = parser.parse_args()
  options = Options(WORK_DIR)
  options.print_info()
  options.clean_tree(True)
  options.download_files()
  options.archive()
  options.make_patch()
  options.parse_spec(args)
  options.make_srpm()
  options.clean_tree(False)
  sys.exit(0)

if __name__ == "__main__":
  main()

# vim:expandtab:tabstop=2:shiftwidth=2:softtabstop=2
