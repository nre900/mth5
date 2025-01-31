# -*- coding: utf-8 -*-
"""
Base Group Class
====================

Contains all the base functions that will be used by group classes.

Created on Fri May 29 15:09:48 2020

:copyright:
    Jared Peacock (jpeacock@usgs.gov)

:license:
    MIT
"""
# =============================================================================
# Imports
# =============================================================================
import inspect
import weakref

import h5py

from mt_metadata import timeseries as metadata
from mt_metadata.transfer_functions.tf import TransferFunction
from mt_metadata.base import Base

from mth5.helpers import get_tree
from mth5.utils.exceptions import MTH5Error
from mth5.helpers import to_numpy_type, from_numpy_type
from mth5.utils.mth5_logger import setup_logger

# make a dictionary of available metadata classes
meta_classes = dict(inspect.getmembers(metadata, inspect.isclass))
meta_classes["TransferFunction"] = TransferFunction
# =============================================================================
#
# =============================================================================
class BaseGroup:
    """
    Generic object that will have functionality for reading/writing groups,
    including attributes. To access the hdf5 group directly use the
    `BaseGroup.hdf5_group` property.

    >>> base = BaseGroup(hdf5_group)
    >>> base.hdf5_group.ref
    <HDF5 Group Reference>

    .. note:: All attributes should be input into the metadata object, that
             way all input will be validated against the metadata standards.
             If you change attributes in metadata object, you should run the
             `BaseGroup.write_metadata` method.  This is a temporary solution
             working on an automatic updater if metadata is changed.

    >>> base.metadata.existing_attribute = 'update_existing_attribute'
    >>> base.write_metadata()

    If you want to add a new attribute this should be done using the
    `metadata.add_base_attribute` method.

    >>> base.metadata.add_base_attribute('new_attribute',
    ...                                  'new_attribute_value',
    ...                                  {'type':str,
    ...                                   'required':True,
    ...                                   'style':'free form',
    ...                                   'description': 'new attribute desc.',
    ...                                   'units':None,
    ...                                   'options':[],
    ...                                   'alias':[],
    ...                                   'example':'new attribute'})

    Includes intializing functions that makes a summary table and writes
    metadata.

    """

    def __init__(self, group, group_metadata=None, **kwargs):
        self.compression = None
        self.compression_opts = None
        self.shuffle = False
        self.fletcher32 = False

        self.logger = setup_logger(f"{__name__}.{self._class_name}")

        # make sure the reference to the group is weak so there are no lingering
        # references to a closed HDF5 file.
        if group is not None and isinstance(group, (h5py.Group, h5py.Dataset)):
            self.hdf5_group = weakref.ref(group)()

        # initialize metadata
        self._initialize_metadata()

        # if metadata, make sure that its the same class type
        if group_metadata is not None:
            self.metadata = group_metadata

            # write out metadata to make sure that its in the file.
            self.write_metadata()
        else:
            self.read_metadata()

        # if any other keywords
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __str__(self):
        try:
            self.hdf5_group.ref

            return get_tree(self.hdf5_group)
        except ValueError:
            msg = "MTH5 file is closed and cannot be accessed."
            self.logger.warning(msg)
            return msg

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        raise MTH5Error("Cannot test equals yet")

    # Iterate over key, value pairs
    def __iter__(self):
        return self.hdf5_group.items().__iter__()

    @property
    def _class_name(self):
        return self.__class__.__name__.split("Group")[0]

    def _initialize_metadata(self):
        """
        Initialize metadata with custom attributes

        :return: DESCRIPTION
        :rtype: TYPE

        """

        self._metadata = Base()
        if self._class_name not in ["Standards"]:
            try:
                self._metadata = meta_classes[self._class_name]()
            except KeyError:
                self._metadata = Base()

        # add 2 attributes that will help with querying
        # 1) the metadata class name
        self._metadata.add_base_attribute(
            "mth5_type",
            self._class_name.split("Group")[0],
            {
                "type": str,
                "required": True,
                "style": "free form",
                "description": "type of group",
                "units": None,
                "options": [],
                "alias": [],
                "example": "group_name",
                "default": None,
            },
        )

        # 2) the HDF5 reference that can be used instead of paths
        self._metadata.add_base_attribute(
            "hdf5_reference",
            self.hdf5_group.ref,
            {
                "type": "h5py_reference",
                "required": True,
                "style": "free form",
                "description": "hdf5 internal reference",
                "units": None,
                "options": [],
                "alias": [],
                "example": "<HDF5 Group Reference>",
                "default": "none",
            },
        )

    @property
    def metadata(self):
        """Metadata for the Group based on mt_metadata.timeseries"""
        return self._metadata

    @metadata.setter
    def metadata(self, metadata_object):
        """
        Do some validating when setting metadata object

        :param metadata_object: DESCRIPTION
        :type metadata_object: TYPE
        :return: DESCRIPTION
        :rtype: TYPE

        """

        if not isinstance(metadata_object, (type(self._metadata), Base)):
            msg = (
                f"Metadata must be of type {meta_classes[self._class_name]} "
                f"not {type(metadata_object)}"
            )
            self.logger.error(msg)
            raise MTH5Error(msg)

        self._metadata.from_dict(metadata_object.to_dict())

        self._metadata.mth5_type = self._class_name
        self._metadata.hdf5_reference = self.hdf5_group.ref

    @property
    def groups_list(self):
        return list(self.hdf5_group.keys())

    @property
    def dataset_options(self):
        return {
            "compression": self.compression,
            "compression_opts": self.compression_opts,
            "shuffle": self.shuffle,
            "fletcher32": self.fletcher32,
        }

    def read_metadata(self):
        """
        read metadata from the HDF5 group into metadata object

        """
        meta_dict = dict(self.hdf5_group.attrs)
        for key, value in meta_dict.items():
            meta_dict[key] = from_numpy_type(value)
        self.metadata.from_dict({self._class_name: meta_dict})

    def write_metadata(self):
        """
        Write HDF5 metadata from metadata object.

        """

        for key, value in self.metadata.to_dict(single=True).items():
            value = to_numpy_type(value)
            self.logger.debug("wrote metadata {0} = {1}".format(key, value))
            self.hdf5_group.attrs.create(key, value)

    def initialize_group(self, **kwargs):
        """
        Initialize group by making a summary table and writing metadata

        """
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.write_metadata()
