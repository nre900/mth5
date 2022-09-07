# -*- coding: utf-8 -*-
"""
Test time series

Created on Tue Jun 30 16:38:27 2020

:copyright:
    author: Jared Peacock
    
:license:
    MIT
    
"""
# =============================================================================
# imports
# =============================================================================

import unittest

import numpy as np

from mth5.timeseries import ChannelTS, RunTS
from mth5.utils.exceptions import MTTSError

from mt_metadata.utils.mttime import MTime
from mt_metadata.timeseries.filters import (
    PoleZeroFilter,
    ChannelResponseFilter,
)

# =============================================================================
# test run
# =============================================================================
class TestRunTS(unittest.TestCase):
    def setUp(self):
        self.run = RunTS()
        self.maxDiff = None
        self.start = "2015-01-08T19:49:18+00:00"
        self.end = "2015-01-08T19:57:50.00000"
        self.sample_rate = 8
        self.npts = 4096

        pz = PoleZeroFilter(
            units_in="volts", units_out="nanotesla", name="instrument_response"
        )
        pz.poles = [
            (-6.283185 + 10.882477j),
            (-6.283185 - 10.882477j),
            (-12.566371 + 0j),
        ]
        pz.zeros = []
        pz.normalization_factor = 18244400

        self.cr = ChannelResponseFilter(filters_list=[pz])

        self.ex = ChannelTS(
            "electric",
            data=np.random.rand(self.npts),
            channel_metadata={
                "electric": {
                    "component": "Ex",
                    "sample_rate": self.sample_rate,
                    "time_period.start": self.start,
                }
            },
            channel_response_filter=self.cr,
        )
        self.ey = ChannelTS(
            "electric",
            data=np.random.rand(self.npts),
            channel_metadata={
                "electric": {
                    "component": "Ey",
                    "sample_rate": self.sample_rate,
                    "time_period.start": self.start,
                }
            },
            channel_response_filter=self.cr,
        )
        self.hx = ChannelTS(
            "magnetic",
            data=np.random.rand(self.npts),
            channel_metadata={
                "magnetic": {
                    "component": "hx",
                    "sample_rate": self.sample_rate,
                    "time_period.start": self.start,
                }
            },
            channel_response_filter=self.cr,
        )
        self.hy = ChannelTS(
            "magnetic",
            data=np.random.rand(self.npts),
            channel_metadata={
                "magnetic": {
                    "component": "hy",
                    "sample_rate": self.sample_rate,
                    "time_period.start": self.start,
                }
            },
            channel_response_filter=self.cr,
        )
        self.hz = ChannelTS(
            "magnetic",
            data=np.random.rand(self.npts),
            channel_metadata={
                "magnetic": {
                    "component": "hz",
                    "sample_rate": self.sample_rate,
                    "time_period.start": self.start,
                }
            },
            channel_response_filter=self.cr,
        )

        self.run.set_dataset([self.ex, self.ey, self.hx, self.hy, self.hz])

    def test_initialize(self):

        with self.subTest("channels"):
            self.assertListEqual(
                ["ex", "ey", "hx", "hy", "hz"], self.run.channels
            )
        with self.subTest("sample rate"):
            self.assertEqual(self.run.sample_rate, self.sample_rate)
        with self.subTest("start"):
            self.assertEqual(self.run.start, MTime(self.start))
        with self.subTest("end"):
            self.assertEqual(self.run.end, MTime(self.end))

    def test_sr_fail(self):
        hz = ChannelTS(
            "magnetic",
            data=np.random.rand(self.npts),
            channel_metadata={
                "magnetic": {
                    "component": "hz",
                    "sample_rate": 1,
                    "time_period.start": self.start,
                }
            },
        )

        self.assertRaises(
            MTTSError,
            self.run.set_dataset,
            [self.ex, self.ey, self.hx, self.hy, hz],
        )

    def test_channels(self):

        for comp in ["ex", "ey", "hx", "hy", "hz"]:
            ch = getattr(self.run, comp)

            with self.subTest(msg=f"{comp} isinstance channel"):
                self.assertIsInstance(ch, ChannelTS)
            with self.subTest(msg=f"{comp} sample rate"):
                self.assertEqual(ch.sample_rate, self.sample_rate)
            with self.subTest(msg=f"{comp} start"):
                self.assertEqual(ch.start, MTime(self.start))
            with self.subTest(msg=f"{comp} end"):
                self.assertEqual(ch.end, MTime(self.end))
            with self.subTest(msg=f"{comp} component"):
                self.assertEqual(ch.component, comp)

            with self.subTest(msg=f"{comp} filters"):
                self.assertListEqual(
                    self.cr.filters_list,
                    ch.channel_response_filter.filters_list,
                )

    def test_get_channel_fail(self):
        """
        self.run.temperature should return None, because 'temperature' is not in self.channels
        :return:
        """

        self.assertRaises(NameError, getattr, *(self.run, "temperature"))

    def test_wrong_metadata(self):
        self.run.run_metadata.sample_rate = 10
        self.run.validate_metadata()

        with self.subTest("sample rate"):
            self.assertEqual(
                self.ex.sample_rate, self.run.run_metadata.sample_rate
            )
        with self.subTest("start"):
            self.run.run_metadata.start = "2020-01-01T00:00:00"
            self.run.validate_metadata()
            self.assertEqual(
                self.run.start, self.run.run_metadata.time_period.start
            )
        with self.subTest("end"):
            self.run.run_metadata.end = "2020-01-01T00:00:00"
            self.run.validate_metadata()
            self.assertEqual(
                self.run.end, self.run.run_metadata.time_period.end
            )

    def test_get_slice(self):

        start = "2015-01-08T19:49:30+00:00"
        npts = 256

        r_slice = self.run.get_slice(start, n_samples=npts)

        with self.subTest("isinstance runts"):
            self.assertIsInstance(r_slice, RunTS)
        with self.subTest("sample rate"):
            self.assertEqual(r_slice.sample_rate, self.sample_rate)
        with self.subTest("start not equal"):
            self.assertNotEqual(r_slice.start, MTime(start))

        with self.subTest("start equal"):
            # the time index does not have a value at the requested location
            # so it grabs the closest one.
            self.assertEqual(r_slice.start, MTime(start) + 0.002930)
        with self.subTest("end"):
            self.assertEqual(
                r_slice.end, MTime("2015-01-08T19:50:01.885714+00:00")
            )

        with self.subTest("npts"):
            self.assertEqual(r_slice.dataset.ex.data.shape[0], npts)

    def test_filters_dict(self):
        self.assertEqual(
            list(self.run.filters.keys()), ["instrument_response"]
        )


# =============================================================================
# run tests
# =============================================================================
if __name__ == "__main__":
    unittest.main()
