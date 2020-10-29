# -*- coding: utf-8 -*-
"""
.. module:: timeseries
   :synopsis: Deal with MT time series
   
.. todo:: Check the conversion to netcdf.  There are some weird serializations of 
lists and arrays that goes on, seems easiest to convert all lists to strings and then
convert them back if read in.


:copyright:
    Jared Peacock (jpeacock@usgs.gov)
    
:license: 
    MIT
"""

# ==============================================================================
# Imports
# ==============================================================================
import logging
import inspect

import numpy as np
import pandas as pd
import xarray as xr
from matplotlib import pyplot as plt

from mth5 import metadata
from mth5.utils.mttime import MTime
from mth5.utils.exceptions import MTTSError

from obspy.core import Trace, Stream

# =============================================================================
# make a dictionary of available metadata classes
# =============================================================================
meta_classes = dict(inspect.getmembers(metadata, inspect.isclass))


def make_dt_coordinates(start_time, sample_rate, n_samples, logger):
    """
        get the date time index from the data

        :param string start_time: start time in time format
        :param float sample_rate: sample rate in samples per seconds
        :param int n_samples: number of samples in time series
        :param :class:`logging.logger` logger: logger class object
        
        :return: date-time index
        
        """

    if sample_rate in [0, None]:
        msg = (
            f"Need to input a valid sample rate. Not {sample_rate}, "
            + "returning a time index assuming a sample rate of 1"
        )
        logger.warning(msg)
        sample_rate = 1

    if start_time is None:
        msg = (
            f"Need to input a start time. Not {start_time}, "
            + "returning a time index with start time of "
            + "1980-01-01T00:00:00"
        )
        logger.warning(msg)
        start_time = "1980-01-01T00:00:00"

    if n_samples < 1:
        msg = f"Need to input a valid n_samples. Not {n_samples}"
        logger.error(msg)
        raise ValueError(msg)

    if not isinstance(start_time, MTime):
        start_time = MTime(start_time)

    dt_freq = "{0:.0f}N".format(1.0e9 / (sample_rate))

    dt_index = pd.date_range(
        start=start_time.iso_str.split("+", 1)[0], periods=n_samples, freq=dt_freq
    )

    return dt_index


# ==============================================================================
# Channel Time Series Object
# ==============================================================================
class ChannelTS:
    """
    
    .. note:: Assumes equally spaced samples from the start time.
    
    The time series is stored in an :class:`xarray.Dataset` that has 
    coordinates of time and is a 1-D array labeled 'data'.  The :class:`xarray.Dataset`
    can be accessed and set from the :attribute:`ts`.  The data is stored in 
    :attribute:'ts.data' and the time index is a coordinate of :attribute:`ts`.
    
    The time coordinate is made from the start time, sample rate and 
    number of samples.  Currently, End time is a derived property and 
    cannot be set. 
    
    Channel time series object is based on xarray and :class:`mth5.metadata` therefore
    any type of interpolation, resampling, groupby, etc can be done using xarray
    methods.
    
    There are 3 metadata classes that hold important metadata
    
        * :class:`mth5.metadata.Station` holds information about the station
        * :class:`mth5.metadata.Run` holds information about the run the channel
        belongs to.
        * :class`mth5.metadata.Channel` holds information specific to the channel.
        
    This way a single channel will hold all information needed to represent the 
    channel.  
    
    
    Example
    ---------
        
        >>> from mth5.timeseries import ChannelTS
        >>> ts_obj = ChannelTS('auxiliary')
        >>> ts_obj.sample_rate = 8
        >>> ts_obj.start = '2020-01-01T12:00:00+00:00'
        >>> ts_obj.ts = range(4096)
        >>> ts_obj.station_metadata.id = 'MT001'
        >>> ts_obj.run_metadata.id = 'MT001a'
        >>> ts_obj.component = 'temperature'
        >>> print(ts_obj)
	        Station      = MT001
	        Run          = MT001a
	        Channel Type = auxiliary
            Component    = temperature
	        Sample Rate  = 8.0
	        Start        = 2020-01-01T12:00:00+00:00
	        End          = 2020-01-01T12:08:31.875000+00:00
	        N Samples    = 4096
            
    Plot time series with xarray
    ------------------------------
    
        >>> p = ts_obj.ts.plot()
        
        

    """

    def __init__(
        self,
        channel_type="auxiliary",
        data=None,
        channel_metadata=None,
        station_metadata=None,
        run_metadata=None,
        **kwargs,
    ):

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.station_metadata = metadata.Station()
        self.run_metadata = metadata.Run()
        self._ts = xr.DataArray([1], coords=[("time", [1])])

        # get correct metadata class
        try:
            self.metadata = meta_classes[channel_type.capitalize()]()
        except KeyError:
            msg = (
                "Channel type is undefined, must be [ electric | "
                + "magnetic | auxiliary ]"
            )
            self.logger.error(msg)
            raise ValueError(msg)

        if channel_metadata is not None:
            if isinstance(channel_metadata, type(self.metadata)):
                self.metadata.from_dict(channel_metadata.to_dict())
                self.logger.debug(
                    "Loading from metadata class {0}".format(type(self.metadata))
                )
            elif isinstance(channel_metadata, dict):
                if not channel_type in list(channel_metadata.keys()):
                    channel_metadata = {channel_type: channel_metadata}
                self.metadata.from_dict(channel_metadata)
                self.logger.debug("Loading from metadata dict")

            else:
                msg = "input metadata must be type {0} or dict, not {1}".format(
                    type(self.metadata), type(channel_metadata)
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        # add station metadata, this will be important when propogating a single
        # channel such that it can stand alone.
        if station_metadata is not None:
            if isinstance(station_metadata, metadata.Station):
                self.station_metadata.from_dict(station_metadata.to_dict())

            elif isinstance(station_metadata, dict):
                if not "Station" in list(station_metadata.keys()):
                    station_metadata = {"Station": station_metadata}
                self.station_metadata.from_dict(station_metadata)
                self.logger.debug("Loading from metadata dict")

            else:
                msg = "input metadata must be type {0} or dict, not {1}".format(
                    type(self.station_metadata), type(station_metadata)
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        # add run metadata, this will be important when propogating a single
        # channel such that it can stand alone.
        if run_metadata is not None:
            if isinstance(run_metadata, metadata.Run):
                self.run_metadata.from_dict(run_metadata.to_dict())

            elif isinstance(run_metadata, dict):
                if not "Run" in list(run_metadata.keys()):
                    run_metadata = {"Run": run_metadata}
                self.run_metadata.from_dict(run_metadata)
                self.logger.debug("Loading from metadata dict")

            else:
                msg = "input metadata must be type {0} or dict, not {1}".format(
                    type(self.run_metadata), type(run_metadata)
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        # input data
        if data is not None:
            self.ts = data

        self.update_xarray_metadata()

        for key in list(kwargs.keys()):
            setattr(self, key, kwargs[key])

    def __str__(self):
        lines = [
            f"Station:      {self.station_metadata.id}",
            f"Run:          {self.run_metadata.id}",
            f"Channel Type: {self.channel_type}",
            f"Component:    {self.component}",
            f"Sample Rate:  {self.sample_rate}",
            f"Start:        {self.start}",
            f"End:          {self.end}",
            f"N Samples:    {self.n_samples}",
        ]

        return "\t\n".join(["Channel Summary:"] + lines)

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):

        if not isinstance(other, ChannelTS):
            raise ValueError(f"Cannot compare ChannelTS with {type(other)}")

        if not other.metadata == self.metadata:
            return False

        if self.ts.equals(other.ts) is False:
            msg = "timeseries are not equal"
            self.logger.info(msg)
            return False

        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        if not isinstance(other, ChannelTS):
            raise ValueError(f"Cannot compare ChannelTS with {type(other)}")

        self.logger.info("Only testing start time")
        if other.start < self.start and other.sample_rate == self.sample_rate:
            return True
        return False

    def __gt__(self, other):
        return not self.__lt__(other)

    ### Properties ------------------------------------------------------------
    @property
    def ts(self):
        return self._ts

    @ts.setter
    def ts(self, ts_arr):
        """
        if setting ts with a pandas data frame, make sure the data is in a
        column name 'data'
        """

        if isinstance(ts_arr, np.ndarray):
            self.logger.debug(f"loading numpy array with shape {ts_arr.shape}")
            dt = make_dt_coordinates(
                self.start, self.sample_rate, ts_arr.size, self.logger
            )
            self._ts = xr.DataArray(ts_arr, coords=[("time", dt)])
            self.update_xarray_metadata()

        elif isinstance(ts_arr, pd.core.frame.DataFrame):
            self.logger.debug(f"loading pandas dataframe with shape {ts_arr.shape}")
            if isinstance(ts_arr.index[0], pd._libs.tslibs.timestamps.Timestamp):
                dt = ts_arr.index
            else:
                dt = make_dt_coordinates(
                    self.start, self.sample_rate, ts_arr["data"].size, self.logger
                )
            try:
                self._ts = xr.DataArray(ts_arr["data"], coords=[("time", dt)])
                self.update_xarray_metadata()

            except AttributeError:
                msg = (
                    "Data frame needs to have a column named `data` "
                    + "where the time series data is stored"
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        elif isinstance(ts_arr, pd.core.series.Series):
            self.logger.debug(f"loading pandas series with shape {ts_arr.shape}")
            if isinstance(ts_arr.index[0], pd._libs.tslibs.timestamps.Timestamp):
                dt = ts_arr.index
            else:
                dt = make_dt_coordinates(
                    self.start, self.sample_rate, ts_arr["data"].size, self.logger
                )

            self._ts = xr.DataArray(ts_arr.values, coords=[("time", dt)])
            self.update_xarray_metadata()

        elif isinstance(ts_arr, xr.DataArray):
            self.logger.debug(f"loading xarra.DataArray with shape {ts_arr.shape}")
            # TODO: need to validate the input xarray
            self._ts = ts_arr
            meta_dict = dict([(k, v) for k, v in ts_arr.attrs.items()])
            self.metadata.from_dict({self.metadata.type: meta_dict})
            self.update_xarray_metadata()

        else:
            msg = (
                "Data type {0} not supported".format(type(ts_arr))
                + ", ts needs to be a numpy.ndarray, pandas DataFrame, "
                + "or xarray.DataArray."
            )
            raise MTTSError(msg)

    @property
    def channel_type(self):
        """ Channel Type """
        return self.metadata._class_name

    @channel_type.setter
    def channel_type(self, value):
        """ change channel type means changing the metadata type """

        if value.lower() != self.metadata._class_name.lower():
            m_dict = self.metadata.to_dict()[self.metadata._class_name]
            try:
                self.metadata = meta_classes[value.capitalize()]()
                msg = (
                    f"Changing metadata to {value.capitalize()}"
                    + "will translate any similar attributes."
                )
                self.logger.info(msg)
            except KeyError:
                msg = (
                    f"Channel type {value} not understood, must be "
                    + "[ Electrict | Magnetic | Auxiliary ]"
                )
                self.logger.error(msg)

            for key in self.metadata.to_dict()[self.metadata._class_name].keys():
                try:
                    self.metadata.set_attr_from_name(key, m_dict[key])
                except KeyError:
                    pass
        return

    def update_xarray_metadata(self):
        """
        Update xarray attrs dictionary with metadata.  Here we are assuming that 
        self.metadata is the parent and attrs in xarray are children because all 
        metadata will be validated by :class:`mth5.metadata` class objects.  
        
        Eventually there should be a way that this is automatic, but I'm not that 
        clever yet.
        
        This should be mainly used internally but gives the user a way to update 
        metadata.  

        """
        self.logger.debug("Updating xarray attributes")

        self.metadata.time_period.start = self.start.iso_no_tz
        self.metadata.time_period.end = self.end.iso_no_tz
        self.metadata.sample_rate = self.sample_rate

        self._ts.attrs.update(self.metadata.to_dict()[self.metadata._class_name])

    @property
    def component(self):
        """ component """
        return self.metadata.component

    @component.setter
    def component(self, comp):
        """ set component in metadata and carry through """
        if self.metadata.type == "electric":
            if comp[0].lower() != "e":
                msg = (
                    "The current timeseries is an electric channel. "
                    "Cannot change channel type, create a new ChannelTS object."
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        elif self.metadata.type == "magnetic":
            if comp[0].lower() not in ["h", "b"]:
                msg = (
                    "The current timeseries is a magnetic channel. "
                    "Cannot change channel type, create a new ChannelTS object."
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        if self.metadata.type == "auxiliary":
            if comp[0].lower() in ["e", "h", "b"]:
                msg = (
                    "The current timeseries is an auxiliary channel. "
                    "Cannot change channel type, create a new ChannelTS object."
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        self.metadata.component = comp
        self.update_xarray_metadata()

    # --> number of samples just to make sure there is consistency
    @property
    def n_samples(self):
        """number of samples"""
        return int(self.ts.size)

    @n_samples.setter
    def n_samples(self, n_samples):
        """number of samples (int)"""
        self.logger.warning(
            "Cannot set the number of samples. Use `ChannelTS.resample` or `get_slice`"
        )

    @property
    def has_data(self):
        """
        check to see if there is an index in the time series
        """
        if len(self._ts) > 1:
            if isinstance(
                self.ts.indexes["time"][0], pd._libs.tslibs.timestamps.Timestamp
            ):
                return True
            return False
        else:
            return False

    # --> sample rate
    @property
    def sample_rate(self):
        """sample rate in samples/second"""
        if self.has_data:
            # this is a hack cause I don't understand how the freq can be none,
            # but this is the case with xarray if you interpolate data
            if self._ts.coords.indexes["time"][0].freq is None:
                freq = pd.infer_freq(self._ts.coords.indexes["time"])
                if "L" in freq:
                    sr = 1.0 / (1e-3 * float(freq[0:-1]))
                elif "U" in freq:
                    sr = 1.0 / (1e-6 * float(freq[0:-1]))
                elif "N" in freq:
                    sr = 1.0 / (1e-9 * float(freq[0:-1]))

            else:
                sr = 1e9 / self._ts.coords.indexes["time"][0].freq.nanos
        else:
            self.logger.debug("Data has not been set yet, sample rate is from metadata")
            sr = self.metadata.sample_rate
            if sr is None:
                sr = 0.0
        return np.round(sr, 0)

    @sample_rate.setter
    def sample_rate(self, sample_rate):
        """
        sample rate in samples/second

        type float
        """
        if self.metadata.sample_rate not in [0.0, None]:
            self.logger.warning(
                "Setting ChannelTS.metadata.sample_rate. "
                + "If you want to change existing time series sample"
                + " rate use method `resample`."
            )
        self.metadata.sample_rate = sample_rate
        self.update_xarray_metadata()

    ## set time and set index
    @property
    def start(self):
        """MTime object"""
        if self.has_data:
            return MTime(self._ts.coords.indexes["time"][0].isoformat())
        else:
            self.logger.debug(
                "Data not set yet, pulling start time from "
                + "metadata.time_period.start"
            )
            return MTime(self.metadata.time_period.start)

    @start.setter
    def start(self, start_time):
        """
        start time of time series in UTC given in some format or a datetime
        object.

        Resets epoch seconds if the new value is not equivalent to previous
        value.

        Resets how the ts data frame is indexed, setting the starting time to
        the new start time.
        
        :param start_time: start time of time series, can be string or epoch seconds
        
        """

        if not isinstance(start_time, MTime):
            start_time = MTime(start_time)

        self.metadata.time_period.start = start_time.iso_str
        if self.has_data:
            if start_time == MTime(self.ts.coords.indexes["time"][0].isoformat()):
                return
            else:
                new_dt = make_dt_coordinates(
                    start_time, self.sample_rate, self.n_samples, self.logger
                )
                self.ts.coords["time"] = new_dt

        # make a time series that the data can be indexed by
        else:
            self.logger.debug("No data, just updating metadata start")

        self.update_xarray_metadata()

    @property
    def end(self):
        """MTime object"""
        if self.has_data:
            return MTime(self._ts.coords.indexes["time"][-1].isoformat())
        else:
            self.logger.debug(
                "Data not set yet, pulling end time from " + "metadata.time_period.end"
            )
            return MTime(self.metadata.time_period.end)

    @end.setter
    def end(self, end_time):
        """
        end time of time series in UTC given in some format or a datetime
        object.

        Resets epoch seconds if the new value is not equivalent to previous
        value.

        Resets how the ts data frame is indexed, setting the starting time to
        the new start time.
        """
        self.logger.warning(
            "Cannot set `end`. If you want a slice, then " + "use get_slice method"
        )

    def get_slice(self, start, end):
        """
        Get a slice from the time series given a start and end time.
        
        Looks for >= start & <= end
        
        Uses loc to be exact with milliseconds
        
        :param start: DESCRIPTION
        :type start: TYPE
        :param end: DESCRIPTION
        :type end: TYPE
        :return: DESCRIPTION
        :rtype: TYPE

        """

        if not isinstance(start, MTime):
            start = MTime(start)
        if not isinstance(end, MTime):
            end = MTime(end)

        new_ts = self.ts.loc[
            (self.ts.indexes["time"] >= start.iso_no_tz)
            & (self.ts.indexes["time"] <= end.iso_no_tz)
        ]
        new_ts.attrs["time_period.start"] = new_ts.coords.indexes["time"][0].isoformat()
        new_ts.attrs["time_period.end"] = new_ts.coords.indexes["time"][-1].isoformat()

        return new_ts

    # decimate data
    def resample(self, dec_factor=1, inplace=False):
        """
        decimate the data by using scipy.signal.decimate

        :param dec_factor: decimation factor
        :type dec_factor: int

        * refills ts.data with decimated data and replaces sample_rate

        """

        new_dt_freq = "{0:.0f}N".format(1e9 / (self.sample_rate / dec_factor))

        new_ts = self.ts.resample(time=new_dt_freq).nearest(tolerance=new_dt_freq)
        new_ts.attrs["sample_rate"] = self.sample_rate / dec_factor
        self.metadata.sample_rate = new_ts.attrs["sample_rate"]

        if inplace:
            self.ts = new_ts

        else:
            new_ts.attrs.update(self.metadata.to_dict()[self.metadata._class_name])
            # return new_ts
            return ChannelTS(self.metadata.type, data=new_ts, metadata=self.metadata)

    def to_obspy_trace(self):
        """
        Convert the time series to an :class:`obspy.core.trace.Trace` object.  This
        will be helpful for converting between data pulled from IRIS and data going
        into IRIS.
        
        :return: DESCRIPTION
        :rtype: TYPE

        """

        obspy_trace = Trace(self.ts.data)
        obspy_trace.stats.channel = self.component
        obspy_trace.stats.starttime = self.start.iso_str
        obspy_trace.stats.sampling_rate = self.sample_rate
        obspy_trace.stats.station = self.station_metadata.fdsn.id

        return obspy_trace

    def from_obspy_trace(self, obspy_trace):
        """
        Fill data from an :class:`obspy.core.Trace`
        
        :param obspy.core.trace obspy_trace: Obspy trace object
        
        """

        if not isinstance(obspy_trace, Trace):
            msg = f"Input must be obspy.core.Trace, not {type(obspy_trace)}"
            self.logger.error(msg)
            raise MTTSError(msg)

        if obspy_trace.stats.channel[0].lower() in ["e", "q"]:
            self.metadata = metadata.Electric()
        elif obspy_trace.stats.channel[0].lower() in ["h", "b", "f"]:
            self.metadata = metadata.Magnetic()
        else:
            self.metadata = metadata.Auxiliary()

        self.metadata.component = obspy_trace.stats.channel
        self.start = obspy_trace.stats.starttime.isoformat()
        self.sample_rate = obspy_trace.stats.sampling_rate
        self.station_metadata.fdsn.id = obspy_trace.stats.station
        self.station_metadata.fdsn.network = obspy_trace.stats.network
        self.station_metadata.id = obspy_trace.stats.station
        self.metadata.units = "counts"
        self.ts = obspy_trace.data


# =============================================================================
# run container
# =============================================================================
class RunTS:
    """
    holds all run ts in one aligned array
    
    components --> {'ex': ex_xarray, 'ey': ey_xarray}
    
    """

    def __init__(self, array_list=None, run_metadata=None, station_metadata=None):

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.metadata = metadata.Run()
        self.station_metadata = metadata.Station()
        self._dataset = xr.Dataset()

        if run_metadata is not None:
            if isinstance(run_metadata, dict):
                # make sure the input dictionary has the correct form
                if "run" not in list(run_metadata.keys()):
                    run_metadata = {"run": run_metadata}
                self.metadata.from_dict(run_metadata)

            elif isinstance(run_metadata, metadata.Run):
                self.metadata.from_dict(run_metadata.to_dict())
            else:
                msg = (
                    "Input metadata must be a dictionary or Run object, "
                    f"not {type(run_metadata)}"
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        # add station metadata, this will be important when propogating a run
        if station_metadata is not None:
            if isinstance(station_metadata, metadata.Station):
                self.station_metadata.from_dict(station_metadata.to_dict())

            elif isinstance(station_metadata, dict):
                if not "Station" in list(station_metadata.keys()):
                    station_metadata = {"Station": station_metadata}
                self.station_metadata.from_dict(station_metadata)
                self.logger.debug("Loading from metadata dict")

            else:
                msg = "input metadata must be type {0} or dict, not {1}".format(
                    type(self.station_metadata), type(station_metadata)
                )
                self.logger.error(msg)
                raise MTTSError(msg)

        if array_list is not None:
            self.dataset = array_list

    def __str__(self):
        s_list = [
            f"Station:     {self.station_metadata.fdsn.id}",
            f"Run:         {self.metadata.id}",
            f"Start:       {self.start}",
            f"End:         {self.end}",
            f"Sample Rate: {self.sample_rate}",
            f"Components:  {self.channels}",
        ]
        return "\n\t".join(["RunTS Summary:"] + s_list)

    def __repr__(self):
        return self.__str__()

    def _validate_array_list(self, array_list):
        """ check to make sure all entries are a :class:`ChannelTS` object"""

        if not isinstance(array_list, (tuple, list)):
            msg = f"array_list must be a list or tuple, not {type(array_list)}"
            self.logger.error(msg)
            raise TypeError(msg)

        for index, item in enumerate(array_list):
            if not isinstance(item, ChannelTS):
                msg = f"array entry {index} must be ChannelTS object not {type(item)}"
                self.logger.error(msg)
                raise TypeError(msg)

        # probably should test for sampling rate.
        sr_test = dict([(item.component, (item.sample_rate)) for item in array_list])

        if len(set([v for k, v in sr_test.items()])) != 1:
            msg = f"sample rates are not all the same {sr_test}"
            self.logger.error(msg)
            raise MTTSError(msg)

        return [x.ts for x in array_list]

    def __getattr__(self, name):
        if name in self.channels:
            if name[0].lower() in ["e"]:
                return ChannelTS("electric", self.dataset[name])
            elif name[0].lower() in ["h", "b"]:
                return ChannelTS("magnetic", self.dataset[name])
            else:
                return ChannelTS("auxiliary", self.dataset[name])
        else:
            return getattr(self, name)

    @property
    def has_data(self):
        """ check to see if there is data """
        if len(self.channels) > 0:
            return True
        return False

    @property
    def summarize_metadata(self):
        """
        
        Get a summary of all the metadata
        
        :return: DESCRIPTION
        :rtype: TYPE

        """
        meta_dict = {}
        for comp in self.dataset.data_vars:
            for mkey, mvalue in self.dataset[comp].attrs.items():
                meta_dict[f"{comp}.{mkey}"] = mvalue

        return meta_dict

    def validate_metadata(self):
        """
        Check to make sure that the metadata matches what is in the data set.
        
        updates metadata from the data.
        
        Check the start and end times, channels recorded
        :return: DESCRIPTION
        :rtype: TYPE

        """

        # check sampling rate
        if self.has_data:
            if self.sample_rate != self.metadata.sample_rate:
                msg = (
                    f"sample rate of dataset {self.sample_rate} does not "
                    f"match metadata sample rate {self.metadata.sample_rate} "
                    f"updating metatdata value to {self.sample_rate}"
                )
                self.logger.warning(msg)
                self.metadata.sample_rate = self.sample_rate

            # check start time
            if self.start != self.metadata.time_period.start:
                msg = (
                    f"start time of dataset {self.start} does not "
                    f"match metadata start {self.metadata.time_period.start} "
                    f"updating metatdata value to {self.start}"
                )
                self.logger.warning(msg)
                self.metadata.time_period.start = self.start.iso_str

            # check end time
            if self.end != self.metadata.time_period.end:
                msg = (
                    f"end time of dataset {self.end} does not "
                    f"match metadata end {self.metadata.time_period.end} "
                    f"updating metatdata value to {self.end}"
                )
                self.logger.warning(msg)
                self.metadata.time_period.end = self.end.iso_str

            # update channels recorded
            self.metadata.channels_recorded_auxiliary = []
            self.metadata.channels_recorded_electric = []
            self.metadata.channels_recorded_magnetic = []
            for ch in self.channels:
                if ch[0] in ["e"]:
                    self.metadata.channels_recorded_electric.append(ch)
                elif ch[0] in ["h", "b"]:
                    self.metadata.channels_recorded_magnetic.append(ch)
                else:
                    self.metadata.channels_recorded_auxiliary.append(ch)

    def set_dataset(self, array_list, align_type="outer"):
        """
        
        :param array_list: list of xarrays
        :type array_list: list of :class:`mth5.timeseries.ChannelTS` objects
        :param align_type: how the different times will be aligned
            * ’outer’: use the union of object indexes
            * ’inner’: use the intersection of object indexes
            * ’left’: use indexes from the first object with each dimension
            * ’right’: use indexes from the last object with each dimension
            * ’exact’: instead of aligning, raise ValueError when indexes to
            be aligned are not equal
            * ’override’: if indexes are of same size, rewrite indexes to
            be those of the first object with that dimension. Indexes for
            the same dimension must have the same size in all objects.
        :type align_type: string

        """
        x_array_list = self._validate_array_list(array_list)

        # first need to align the time series.
        x_array_list = xr.align(*x_array_list, join=align_type)

        # input as a dictionary
        xdict = dict([(x.component.lower(), x) for x in x_array_list])
        self._dataset = xr.Dataset(xdict)
        self.validate_metadata()
        self._dataset.attrs.update(self.metadata.to_dict()["run"])

    def add_channel(self, channel):
        """
        Add a channel to the dataset, can be an :class:`xarray.DataArray` or
        :class:`mth5.timeseries.ChannelTS` object.
        
        Need to be sure that the coordinates and dimensions are the same as the
        existing dataset, namely coordinates are time, and dimensions are the same,
        if the dimesions are larger than the existing dataset then the added channel
        will be clipped to the dimensions of the existing dataset.  
        
        If the start time is not the same nan's will be placed at locations where the
        timing does not match the current start time.  This is a feature of xarray.
        
        
        :param channel: a channel xarray or ChannelTS to add to the run
        :type channel: :class:`xarray.DataArray` or :class:`mth5.timeseries.ChannelTS`
        

        """

        if isinstance(channel, xr.DataArray):
            c = ChannelTS()
            c.ts = channel
        elif isinstance(channel, ChannelTS):
            c = channel
        else:
            raise ValueError("Input Channel must be type xarray.DataArray or ChannelTS")

        ### need to validate the channel to make sure sample rate is the same
        if c.sample_rate != self.sample_rate:
            msg = (
                f"Channel sample rate is not correct, current {self.sample_rate} "
                + f"input {c.sample_rate}"
            )
            self.logger.error(msg)
            raise MTTSError(msg)

        ### should probably check for other metadata like station and run?

        self._dataset[c.component] = c.ts

    @property
    def dataset(self):
        return self._dataset

    @dataset.setter
    def dataset(self, array_list):
        msg = (
            "Data will be aligned using the min and max time. "
            "If that is not correct use set_dataset and change the alignment type."
        )
        self.logger.debug(msg)
        self.set_dataset(array_list)

    @property
    def start(self):
        if self.has_data:
            return MTime(self.dataset.coords["time"].to_index()[0].isoformat())
        return self.metadata.time_period.start

    @property
    def end(self):
        if self.has_data:
            return MTime(self.dataset.coords["time"].to_index()[-1].isoformat())
        return self.metadata.time_period.end

    @property
    def sample_rate(self):
        if self.has_data:
            return 1e9 / self.dataset.coords["time"].to_index().freq.n
        return self.metadata.sample_rate

    @property
    def channels(self):
        return [cc for cc in list(self.dataset.data_vars)]

    def to_obspy_stream(self):
        """
        convert time series to an :class:`obspy.core.Stream` which is like a 
        list of :class:`obspy.core.Trace` objects.
        
        :return: An Obspy Stream object from the time series data
        :rtype: :class:`obspy.core.Stream`

        """

        trace_list = []
        for channel in self.channels:
            if channel[0] in ["e"]:
                ch_type = "electric"
            elif channel[0] in ["h", "b"]:
                ch_type = "magnetic"
            else:
                ch_type = "auxiliary"
            ts_obj = ChannelTS(ch_type, self.dataset[channel])
            trace_list.append(ts_obj.to_obspy_trace())

        return Stream(traces=trace_list)

    def from_obspy_stream(self, obspy_stream):
        """
        Get a run from an :class:`obspy.core.stream` which is a list of
        :class:`obspy.core.Trace` objects.
        
        :param obspy_stream: Obspy Stream object
        :type obspy_stream: :class:`obspy.core.Stream`
        

        """

        if not isinstance(obspy_stream, Stream):
            msg = f"Input must be obspy.core.Stream not {type(obspy_stream)}"
            self.logger.error(msg)
            raise MTTSError(msg)

        array_list = []
        station_list = []
        for obs_trace in obspy_stream:
            channel_ts = ChannelTS()
            channel_ts.from_obspy_trace(obs_trace)
            station_list.append(channel_ts.station_metadata.fdsn.id)

            array_list.append(channel_ts)

        ### need to merge metadata into something useful, station name is the only
        ### name that is preserved
        try:
            station = list(set([ss for ss in station_list if ss is not None]))[0]
        except IndexError:
            station = None
            msg = "Could not find station name"
            self.logger.warn(msg)

        self.station_metadata.fdsn.id = station

        self.set_dataset(array_list)

    def plot(self):
        """
        
        plot the time series probably slow for large data sets
        
        :return: DESCRIPTION
        :rtype: TYPE

        """

        n_channels = len(self.channels)

        fig = plt.figure()
        fig.subplots_adjust(hspace=0)
        ax1 = fig.add_subplot(n_channels, 1, 1)
        self.dataset[self.channels[0]].plot()
        ax_list = [ax1]
        for ii, comp in enumerate(self.channels[1:], 2):
            ax = plt.subplot(n_channels, 1, ii, sharex=ax1)
            self.dataset[comp].plot()
            ax_list.append(ax)

        for ax in ax_list:
            ax.grid(which="major", color=(0.65, 0.65, 0.65), ls="--", lw=0.75)
            ax.grid(which="minor", color=(0.85, 0.85, 0.85), ls="--", lw=0.5)
            ax.set_axisbelow(True)
