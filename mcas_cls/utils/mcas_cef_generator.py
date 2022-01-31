"""MCAS CEF Generator."""
import io
import collections
import csv
import datetime
import datetime as dt
import re
import socket
import time

from .mcas_constants import (
    SEVERITY_MAP,
    SEVERITY_UNKNOWN,
)
from .mcas_exceptions import (
    CEFValueError,
    CEFTypeError,
)


class CEFGenerator(object):
    """CEF Generator class."""

    def __init__(self, extensions, delimiter, cef_version, logger):
        """Init method."""
        self.logger = logger
        self.cef_version = cef_version  # Version of CEF being used
        self.extensions = extensions  # CSV string having information of all the available CEF fields
        self.extension = collections.namedtuple(
            "Extension", ("key_name", "sanitizer")
        )
        self.extension_converter = collections.namedtuple(
            "Extension", ("key_name", "converter")
        )
        self._prefix_field_str_sanitizer = self.str_sanitizer(
            "[^\r\n]*", escape_chars=delimiter
        )
        self._prefix_field_float_sanitizer = self.float_sanitizer()
        self._equals_escaper = self.escaper("=")
        self._severity_sanitizer = self.str_sanitizer(
            "Unknown|Low|Medium|High|Very-High"
        )
        self.valid_extensions = self._valid_extensions()
        self.extension_converters = self._type_converter()
        self.delimiter = delimiter

    def escaper(self, special_chars):
        """Escape the given special characters.

        :param special_chars: The special characters to be escaped
        :return: Escaped special characters
        """
        strip_escaped_re = re.compile(r"\\([{}\\])".format(special_chars))
        do_escape_re = re.compile(r"([{}\\])".format(special_chars))

        def escape(s):
            stripped = strip_escaped_re.sub(r"\1", s)
            return do_escape_re.sub(r"\\\1", stripped)

        return escape

    def ensure_in_range(self, debug_name, min, max, num):
        """Check whether the given value is in given range or not.

        :param debug_name: The human readable name of the value being verified
        :param min: Min value of threshold
        :param max: Max value of threshold
        :param num: The value to be verified
        :raises CEFValueError in case of value is not in given threshold
        """
        if max is None:
            if min is not None and num < min:
                raise CEFValueError(
                    "{}: {} less than {}".format(debug_name, num, min)
                )
        elif min is None:
            if max is not None and num > max:
                raise CEFValueError(
                    "{}: {} greater than {}".format(debug_name, num, max)
                )
        elif not min <= num <= max:
            raise CEFValueError(
                "{}: {} out of range {}-{}".format(debug_name, num, min, max)
            )

    def int_sanitizer(self, max=None, min=None):
        """Wrap function for ensuring the given value is integer and in given range.

        :param max: Min value of threshold
        :param min: Max value of threshold
        :raises CEFTypeError in case of value other than integer
        :return: Function to sanitize the given integer value
        """

        def sanitize(n, debug_name):
            if not isinstance(n, int):
                raise CEFTypeError(
                    "{}: Expected int, got {}".format(debug_name, type(n))
                )
            self.ensure_in_range(debug_name, min, max, n)
            return str(n)

        return sanitize

    def float_sanitizer(self):
        """Wrap function for ensuring the given value is float.

        :return: Function to sanitize the given float value
        :raises CEFTypeError in case of value other than float
        """

        def sanitize(n, debug_name):
            if not isinstance(n, float):
                raise CEFTypeError(
                    "{}: Expected float, got {}".format(debug_name, type(n))
                )
            else:
                return str(n)

        return sanitize

    def str_sanitizer(
        self, regex_str=".*", escape_chars="", min_len=0, max_len=None
    ):
        """Wrap function for ensuring the given value is string and has specific properties.

        :param: regex_str: The regex to be matched in given string
        :param: escape_chars: The characters to be escaped in given string
        :param: min_len: The min possible length of given string
        :param: max_len: The max possible length of given string
        :return: Function to sanitize the given float value
        :raises CEFTypeError in case of value other than float
        """
        regex = re.compile("^{}$".format(regex_str), re.DOTALL)
        escape = self.escaper(escape_chars)

        def sanitize(s, debug_name):
            if not isinstance(s, str):
                raise CEFTypeError(
                    "{}: Expected str, got {}".format(debug_name, type(s))
                )
            if not regex.match(s):
                raise CEFTypeError(
                    "{}: {!r} did not match regex {!r}".format(
                        debug_name, s, regex_str
                    )
                )

            s = s.encode("unicode_escape").decode("utf-8")
            escaped = escape(s)
            if max_len is None and not min_len:
                return escaped

            byte_len = len(escaped)
            if (max_len is None) and (byte_len < min_len):
                raise CEFTypeError(
                    "{}: String shorter than {} bytes".format(
                        debug_name, min_len
                    )
                )

            if (max_len is not None) and not min_len <= byte_len <= max_len:
                raise CEFTypeError(
                    "{}: String length out of range {}-{}".format(
                        debug_name, min_len, max_len
                    )
                )
            return escaped

        return sanitize

    def datetime_sanitizer(self):
        """Wrap function for ensuring the given value is a valid date time instance.

        :raises CEFTypeError in case of value other than datetime
        :return: Function to sanitize the given datetime value
        """

        def sanitize(t, debug_name):
            if not isinstance(t, dt.datetime):
                raise CEFTypeError(
                    "{}: Expected datetime, got {}".format(debug_name, type(t))
                )
            else:
                return str(t.timestamp()).split(".")[0]

        return sanitize

    def string_converter(self):
        """Wrap function for converting given value to string.

        :raises CEFTypeError in case when value is not string compatible
        :return: Function to convert type of given value to string
        """

        def convert(val, debug_name):
            try:
                return str(val)
            except Exception:
                raise CEFTypeError(
                    "{}: Error occurred while converting to string".format(
                        debug_name
                    )
                )

        return convert

    def int_converter(self):
        """Wrap function for converting given value to integer.

        :raises CEFTypeError in case when value is not integer compatible
        :return: Function to convert type of given value to integer
        """

        def convert(val, debug_name):
            try:
                return int(val)
            except Exception:
                raise CEFTypeError(
                    "{}: Error occurred while converting to integer".format(
                        debug_name
                    )
                )

        return convert

    def float_converter(self):
        """Wrap function for converting given value to floating point.

        :raises CEFTypeError in case when value is not float compatible
        :return: Function to convert type of given value to integer
        """

        def convert(val, debug_name):
            try:
                return float(val)
            except Exception:
                raise CEFTypeError(
                    "{}: Error occurred while converting to float".format(
                        debug_name
                    )
                )

        return convert

    def datetime_converter(self):
        """Wrap function for converting given value to datetime object.

        :raises CEFTypeError in case when value is not datetime compatible
        :return: Function to convert type of given value to datetime
        """

        def convert(val, debug_name):
            try:
                return datetime.datetime.fromtimestamp(val)
            except Exception as err:
                raise CEFTypeError(
                    "{}: Error occurred while converting to datetime: {}".format(
                        debug_name, err
                    )
                )

        return convert

    def _type_converter(self):
        """Read the CEF extension CSV file and creates the dict for data type converters.

        :param fname:Name of the extension file to be read
        :return: Dict object having details of all the available CEF fields and its type converters
        """
        converters = {
            "String": self.string_converter(),
            "Time Stamp": self.datetime_converter(),
            "Integer": self.int_converter(),
            "Floating Point": self.float_converter(),
            "IPv4 Address": self.string_converter(),
            "IPv6 address": self.string_converter(),
            "MAC Address": self.string_converter(),
            "IP Address": self.string_converter(),
        }

        # Read the CSV and create key-converter dict
        try:
            return {
                record["CEF Key Name"]: self.extension_converter(
                    key_name=record["CEF Key Name"],
                    converter=converters[record["Data Type"]],
                )
                for record in csv.DictReader(
                    io.StringIO(self.extensions), strict=True
                )
            }
        except Exception as err:
            self.logger.error(
                "Error occurred while parsing CEF validation CSV. Error: {}".format(
                    str(err)
                )
            )
            raise

    def _valid_extensions(self):
        """Read the given CEF extension CSV file and creates the dict for each provided values with its sanitizers.

        :return: Dict object having details of all the available CEF fields and its sanitizers
        """
        # Initialize the sanitizers for different data types
        # ipv4_addr_re = r"\.".join([r"\d{1,3}"] * 4)
        ipv4_addr_re = (
            r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4]"
            r"[0-9]|25[0-5])$"
        )
        ipv4_addr = self.str_sanitizer(ipv4_addr_re)
        ipv6_addr_re = r"\:".join(
            ["[0-9a-fA-F]{1,4}"] * 8
        )  # only complete ipv6 address accepted
        ipv6_addr = self.str_sanitizer(ipv6_addr_re)
        ip_addr = self.str_sanitizer(
            r"(" + ipv6_addr_re + r"|" + ipv4_addr_re + r")"
        )
        mac_addr = self.str_sanitizer(r"\:".join(["[0-9a-fA-F]{2}"] * 6))
        str_lens = [31, 40, 63, 100, 128, 200, 255, 1023, 2048, 4000, 8000]
        sanitizers = {
            "IPv4 Address": {"": ipv4_addr},
            "IPv6 address": {"": ipv6_addr},
            "IP Address": {"": ip_addr},
            "MAC Address": {"": mac_addr},
            "Time Stamp": {"": self.datetime_sanitizer()},
            "Floating Point": {"": self.float_sanitizer()},
            "Integer": {
                "": self.int_sanitizer(),
                "65535": self.int_sanitizer(min=0, max=65535),
            },
            "String": dict(
                [("", self.str_sanitizer())]
                + [
                    (str(str_len), self.str_sanitizer(max_len=str_len))
                    for str_len in str_lens
                ]
            ),
        }

        # Parse the CSV and create key-sanitizer dict
        try:
            return {
                record["CEF Key Name"]: self.extension(
                    key_name=record["CEF Key Name"],
                    sanitizer=sanitizers[record["Data Type"]][
                        record["Length"]
                    ],
                )
                for record in csv.DictReader(
                    io.StringIO(self.extensions), strict=True
                )
            }
        except Exception as err:
            self.logger.error(
                "Error occurred while parsing CEF validation CSV. Error: {}".format(
                    str(err)
                )
            )
            raise

    def get_header_value(self, header, headers):
        """Fetch sanitized value of header from given configured headers dict.

        :param header: The header for which sanitized value is to be fetched
        :param headers: Configured headers
        :return: Sanitized value
        """
        if header == "Severity":
            return self._severity_sanitizer(headers[header], header)
        return self._prefix_field_str_sanitizer(headers[header], header)

    def log_invalid_header(
        self, possible_headers, headers, data_type, subtype
    ):
        """Issue log in case of invalid header found in mapping file.

        :param possible_headers: Possible CEF headers
        :param headers: Configured headers
        :param data_type: Data type for which CEF event is being generated
        :param subtype: Subtype of data type for which CEF event is being generated
        """
        for configured_header in list(headers.keys()):
            if configured_header not in possible_headers:
                self.logger.error(
                    '[{}][{}]: Found invalid header configured in mcas mapping file: "{}". Header '
                    "field will be ignored.".format(
                        data_type, subtype, configured_header
                    )
                )

    @staticmethod
    def _get_hostname():
        """Fetch hostname if available, else fetches IP Address.

        :return: Hostname
        """
        hostname = socket.gethostname()
        if hostname:
            return hostname

        # Get IP Address
        socket_obj = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        socket_obj.connect(("8.8.8.8", 80))  # NOSONAR
        hostname = socket_obj.getsockname()[0]
        socket_obj.close()

        return hostname

    def get_cef_event(self, headers, extensions, data_type, subtype):
        """Produce a CEF compliant message from the arguments.

        :param data_type: type of data being transformed (alert/event)
        :param subtype: subtype of data being transformed
        :param headers: Headers of CEF event
        :parameter dict extensions: key-value pairs for event metadata.
        """
        extension_strs = {}
        for name, value in extensions.items():

            # First convert the incoming value from Netskope to appropriate data type
            try:
                value = self.extension_converters[name].converter(value, name)
            except KeyError:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Could not '
                    'find the field in the file "valid_extensions.csv". Field will be ignored'.format(
                        data_type, subtype, name
                    )
                )
                continue
            except Exception as err:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Error: {}. '
                    "Field will be ignored".format(
                        data_type, subtype, name, str(err)
                    )
                )
                continue

            # Validate and sanitise (if required) the incoming value from Netskope before mapping it CEF
            try:
                extension_strs[
                    self.valid_extensions[name].key_name
                ] = self._equals_escaper(
                    self.valid_extensions[name].sanitizer(value, name)
                )
            except KeyError:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Could not '
                    'find the field in the file "valid_extensions.csv". Field will be ignored'.format(
                        data_type, subtype, name
                    )
                )
            except Exception as err:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Error: {}. '
                    "Field will be ignored".format(
                        data_type, subtype, name, str(err)
                    )
                )

        extensions_str = " ".join(
            sorted("{}={}".format(k, v) for k, v in extension_strs.items())
        )

        possible_headers = [
            "Device Vendor",
            "Device Product",
            "Device Version",
            "Device Event Class ID",
            "Name",
            "Severity",
        ]

        self.log_invalid_header(possible_headers, headers, data_type, subtype)

        hostname = self._get_hostname()

        # Append the CEF version
        cef_components = [
            "{} {} CEF:{}".format(
                time.strftime("%b %d %H:%M:%S", time.localtime(time.time())),
                hostname,
                self.cef_version,
            )
        ]

        # Append other headers if available
        for header in possible_headers:
            if header in headers:
                try:
                    if header == "Severity":
                        headers[header] = SEVERITY_MAP.get(
                            str(headers[header]).lower(), SEVERITY_UNKNOWN
                        )
                    cef_components.append(
                        self.get_header_value(header, headers)
                    )
                except Exception as err:
                    self.logger.error(
                        '[{}][{}]: An error occurred while generating CEF data for header field: "{}". Error: {}. '
                        "Field will be ignored".format(
                            data_type, subtype, header, str(err)
                        )
                    )

        # Append extension string
        cef_components.append(extensions_str)

        # Join every CEF component with given delimiter
        return self.delimiter.join(cef_components)
