# -*- coding: utf-8 -*-
"""
Created on Wed May 10 11:46:20 2017

@author: shendric
"""

import warnings
from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
import os
import struct
import simplejson


class OrbitThicknessBaseClass(object):

    # define data types of parameters (default: single precision float)
    dtype = defaultdict(lambda: "f4", timestamp=object)

    def __init__(self):
        self.filename = None
        self.track_id = "n/a"
        self.cs2_orbit_id = "n/a"
        self.timestamp = None
        self.longitude = None
        self.latitude = None
        self.sea_ice_thickness = None
        self.ice_density = None
        self.snow_depth = None
        self.snow_density = None

    def init_parameter_groups(self, n_records, parameter_list):
        """ Create arrays for given parameters """
        for name in parameter_list:
            array = np.ndarray(shape=n_records, dtype=self.dtype[name])
            setattr(self, name, array)

    def parameter_quickview(self, parameter_name):
        """ Generate a simple matplotlib graph of a given parameter """

        # Some sanity checks
        if self.n_records == 0:
            warnings.warn("No data")
            return

        if self.__class__.__name__ == "OrbitThicknessBaseClass":
            warnings.warn("No quickviews for BaseClass objects")
            return

        if parameter_name not in self.parameter_list:
            warnings.warn("Parameter [%s] does not exist" % parameter_name)
            return

        # Get value for abcissa
        if self.has_timestamp:
            x = self.timestamp
        else:
            x = np.arange(self.n_records)

        # Get parameter
        y = getattr(self, parameter_name)

        label = "(parameter:%s, source:%s, orbit:%s)" % (
                parameter_name, self.source_id, self.cs2_orbit_id)

        # Make the plot
        plt.figure(label)
        plt.plot(x, y, lw=0.5, alpha=0.5)
        plt.scatter(date2num(x), y, marker=".")
        plt.show()

    @property
    def n_records(self):
        return len(self.longitude)

    @property
    def has_timestamp(self):
        return type(self.timestamp) is np.ndarray


class NASAJPLOrbitThickness(OrbitThicknessBaseClass):

    # Metatadata
    source_id = "nasa_jpl"
    source_longname = "NASA-JPL"

    # Has the following parameters
    parameter_list = ["timestamp", "longitude", "latitude", "ice_density",
                      "snow_density", "snow_depth", "sea_ice_thickness"]

    # Parameter properties
    ice_density_is_fixed = True
    snow_density_is_fixed = False

    # Physical parameters
    default_ice_density = 920.0
    water_density = 1024.0

    # Housekeeping
    n_header_lines = 3

    def __init__(self, filename):

        super(NASAJPLOrbitThickness, self).__init__()
        self.filename = filename
        self.parse()

    def parse(self):
        """ Read the file """

        # read the content of the file
        with open(self.filename, "r") as fh:
            content = fh.readlines()

        # remove header
        content = content[self.n_header_lines:]

        # Create the parameter groups
        n_records = len(content)
        self.init_parameter_groups(n_records, self.parameter_list)

        for i, line in enumerate(content):

            array = [float(s) for s in line.split()]

            # compute timestamp
            days = int(array[1])
            seconds = int(array[2])
            musecs = int(1e6*(array[2]-seconds))
            self.timestamp[i] = datetime(int(array[0]), 1, 1) + \
                timedelta(days=days, seconds=seconds, microseconds=musecs)

            # Transfer data
            self.latitude[i] = array[3]
            self.longitude[i] = array[4]
            self.sea_ice_thickness[i] = array[5]
            self.snow_depth[i] = array[6]
            self.snow_density[i] = array[7]

        # fill ice density array with default values
        self.ice_density[:] = self.default_ice_density


class AWIOrbitThickness(OrbitThicknessBaseClass):

    # Metadata
    source_id = "awi"
    source_longname = "AWI"

    # Has the following parameters
    parameter_list = ["timestamp", "longitude", "latitude", "ice_density",
                      "snow_density", "snow_depth", "sea_ice_thickness"]

    # Parameter properties
    ice_density_is_fixed = False
    snow_density_is_fixed = False

    # Housekeeping
    header_size_bytes = 106
    datagroup_byte_size = 8

    def __init__(self, filename, config_filename):

        super(AWIOrbitThickness, self).__init__()
        self.filename = filename
        self.file_def = configuration_file_ordereddict(config_filename)
        self.parse_filename()
        self.parse_content()
        self.construct_data_groups()

    def parse_filename(self):
        """
        Gets Meta Information from filename
        Example filename:
            CS2_021093_20140401T003839_20140401T004237_B001_AWIPROC01.dat
        """
        fbase = file_basename(self.filename)
        strarr = fbase.split('_')
        # Orbit Number
        self.orbit = np.int16(strarr[1])

    def parse_content(self):
        # Read the Header
        self._parse_header()
        # Calculate the number of records
        self._get_n_records()
        # Construct the data groups
        self._construct_datagroups()
        # Parse file content into data array
        self._parse_content()
        # Create attribute for each parameter
        self._create_attributes()

    def construct_data_groups(self):
        datenum = self.get_datagroup("time")
        timestamp = [self._get_datetime(time) for time in datenum]
        self.timestamp = np.array(timestamp)
        self.longitude = self.get_datagroup("lon")
        self.latitude = self.get_datagroup("lat")
        self.ice_density = self.get_datagroup("rho_i")
        self.snow_density = self.get_datagroup("rho_s")
        self.snow_depth = self.get_datagroup("sd")
        self.sea_ice_thickness = self.get_datagroup("sit")

    def get_datagroup(self, tag):
        index = self.registered_datagroups[tag]
        return np.squeeze(self.data[:, index])

    def _parse_header(self):
        with open(self.filename, 'rb') as f:
            header = f.read(self.header_size_bytes)
        self.lon_limit = struct.unpack('<2f', header[0:8])
        self.lat_limit = struct.unpack('<2f', header[8:16])
        self.content_flags = np.array(struct.unpack('<45h', header[16:106]))

    def _parse_content(self):
        struct_record_parser = self._get_struct_record_parser()
        with open(self.filename, 'rb') as f:
            # read header information again (-> Nirvana)
            f.read(self.header_size_bytes)
            # Read full file content
            for i in np.arange(self.nrecs):
                record = f.read(self.record_byte_size)
                self.data[i, :] = struct.unpack(struct_record_parser, record)
        self._is_in_roi = np.full(self.nrecs, True)

    def _create_attributes(self):
        for parameter_name in self.registered_datagroups.keys():
            setattr(self, parameter_name, self.get_datagroup(parameter_name))

    def _get_n_records(self):
        self._file_size = os.path.getsize(self.filename)
        self.n_datagroups = len(self._get_datagroup_indices())
        self.nrecs = (self._file_size - self.header_size_bytes) / (
            self.n_datagroups * self.datagroup_byte_size)
        self.record_byte_size = self.n_datagroups * self.datagroup_byte_size

    def _construct_datagroups(self):
        self.registered_datagroups = {}
        datagroup_keys = list(self.file_def["output"])
        for i, index in enumerate(self._get_datagroup_indices()):
            self.registered_datagroups[datagroup_keys[index]] = i
        self.data = np.ndarray(
            shape=(self.nrecs, self.n_datagroups),
            dtype=np.float64)
        self._in_export = np.ones(shape=(self.nrecs), dtype=np.bool)

    def _get_datagroup_indices(self):
        return np.where(self.content_flags.astype(bool))[0]

    def _get_struct_record_parser(self):
        return "<%gd" % self.n_datagroups

    def _get_datetime(self, timestamp):
        julday = caldate_1900(timestamp)
        timestamp = datetime(
            int(julday["year"]),
            int(julday["month"]),
            int(julday["day"]),
            int(julday["hour"]),
            int(julday["minute"]),
            int(julday["second"]),
            long(julday["msec"]))
        timestamp = timestamp + timedelta(hours=12)
        return timestamp

    def _get_datetime_str(self, datetime):
        datetime_str = '%sT%s' % (
            datetime.strftime('%Y%m%d'),
            datetime.strftime('%H%M%S'))
        return datetime_str

    def _get_datetime_records_str(self, datetime):
        datetime_str = '%sT%s.%03d' % (
            datetime.strftime('%Y-%m-%d'),
            datetime.strftime('%H:%M:%S'),
            datetime.microsecond/1000)
        return datetime_str


def file_basename(filename, fullpath=False):
    """
    Returns the filename without file extension of a give filename (or path)
    """
    strarr = os.path.split(filename)
    file_name = strarr[-1]
    basename = file_name.split(".")[0]
    if fullpath:
        basename = os.path.join(strarr[0], basename)
    # XXX: Sketchy, needs better solution (with access to os documentation)
    return basename


def configuration_file_ordereddict(filename):
    """
    Read a json file and returns its contents

    Args:
        filename (str):
            Full path to configuration file

    Returns (ordereddict):
        Content of configuration files.
    """
    with open(filename, 'r') as filehandle:
        data = simplejson.load(filehandle, object_pairs_hook=OrderedDict)
    return data


def leapyear(year):
    """
    Returns 1 if the provided year is a leap year, 0 if the provided
    year is not a leap year.
    """
    if year % 4 == 0:
        if year % 100 == 0:
            if year % 400 == 0:
                return 1
            else:
                return 0
        else:
            return 1
    else:
        return 0


def caldate_1900(Julian):
    """
    This is nearly a direct translation of a Matlab script to a Python script
    for changing a Julian date into a Gregorian date.
    """
    from math import *

    JulDay = Julian
    if (JulDay < 2440000):
        JulDay = JulDay+2415020+1
    # This is meant to prevent round-off
    JulDay = JulDay+5.0e-9
    # Conversion to a Gregorian date
    j = floor(JulDay)-1721119
    jin = 4*j-1
    y = floor(jin/146097)
    j = jin-146097*y
    jin = floor(j/4)
    jin = 4*jin+3
    j = floor(jin/1461)
    d = floor(((jin-1461*j)+4)/4)
    jin = 5*d-3
    m = floor(jin/153)
    d = floor(((jin-153*m)+5)/5)
    y = y*100+j
    if m < 10:
        mo = m+3
        yr = y
    else:
        mo = m-9
        yr = y+1
    ivd = (1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366)
    ivdl = (1, 32, 61, 92, 122, 153, 183, 214, 245, 275, 306, 336, 367)
    if (leapyear(yr) == 1):
        yday = ivdl[int(mo-1)]+d-1
    else:
        yday = ivd[int(mo-1)]+d-1
    secs = (JulDay % 1)*24*3600
    sec = round(secs)
    hour = floor(sec/3600)
    min = floor((sec % 3600)/60)
    sec = round(sec % 60)
    msec = JulDay*24.0*3600.0
    msec = (msec-np.floor(msec))*1e6
    cal = {'year': yr, 'yearday': yday, 'month': mo, 'day': d,
           'hour': hour, 'minute': min, 'second': sec, "msec": msec}
    return cal

