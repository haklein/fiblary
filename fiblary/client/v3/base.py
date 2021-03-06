#  Copyright 2014 Klaudiusz Staniek
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""
 fiblary.v3.base
 ~~~~~~~~~~~~~~~~~

 Home Center Controller Base Class Implementation

"""

import jsonpath
import logging
import six
import warlock

from fiblary.common import exceptions
from fiblary.common.utils import quote_if_string


_logger = logging.getLogger(__name__)


def _check_items(obj, searches):
    def _check_properties(attr, value):
        properties = getattr(obj, 'properties', None)
        if properties:
            return properties.get(attr) == value
        return False
    found = all(((getattr(obj, attr, None) == value) or
                _check_properties(attr, value)) for (attr, value) in searches)

    return found


class MinimalController(object):
    """Minimal controller class used as a base class for more
    specific controllers.

    It implements simple get method for read only resources.
    """

    RESOURCE = ''
    API_PARAMS = ()
    """API PARAMS can be directly passed to the RESTApi
    This speed up the list operation
    """

    JSON_CONDITION_BASE = "(@.{0}=={1})"

    def __init__(self, http_client, model):
        self.http_client = http_client
        self.model = model

    def get(self, item_id):
        """Returns :class:`warlock.model.Model` object representing an item
        identified by ``item_id``

        :param item_id: This is an id of the requested object. The item_id
        encoded in GET request as the 'id' parameter
        :returns: :class:`warlock.model.Model` object
        """
        params = {"id": item_id}
        try:
            item = self.http_client.get(self.RESOURCE, params=params).json()
        except exceptions.ConnectionError:
            return None
        except exceptions.HTTPNotFound:
            return None

        return self.model(**item)


class ReadOnlyController(MinimalController):
    """Read only controller class used for controllers using get and list
    methods only
    """

    def list(self, **kwargs):
        _logger.debug(self.RESOURCE)
        _logger.debug(type(self))

        # Pop jsonpath if exists and pass the rest of arguments to API
        # for some API calls home center handles additional parameters

        json_path = kwargs.pop('jsonpath', None)

        # Home center ignores unknown parameters so there is no need to
        # remove them from REST reqest.
        try:
            items = self.http_client.get(self.RESOURCE, params=kwargs).json()
        except exceptions.ConnectionError:
            return

        # if there is no explicit defined json_path paramers
        if json_path is None:
            for value in self.API_PARAMS:
                kwargs.pop(value, None)

            condition_expression = ""
            for k, v in six.iteritems(kwargs):
                if k.startswith('p_'):  # search for properties
                    k = "properties." + k[2:]
                condition_expression += self.JSON_CONDITION_BASE.format(
                    k,
                    quote_if_string(v))
                condition_expression += " and "

            if condition_expression is not "":
                # filter the results with json implicit built from
                # remaining parameters

                json_path = "$[?({})]".format(condition_expression[:-5])
                _logger.debug("Implicit JSON Path: {}".format(json_path))

        if json_path:
            _logger.debug("JSON Path: {}".format(json_path))
            filtered_items = jsonpath.jsonpath(items, json_path)
            if filtered_items:
                items = filtered_items
            else:
                return

        for item in items:
            item_obj = self.model(**item)
            if item_obj:
                yield item_obj
            else:
                continue

    def find(self, **kwargs):
        """Find single item with attributes matching ``**kwargs``.
        It also handles nested properties as a keywords.
        """
        num_matches = 0
        found = None
        items = self.list(**kwargs)
        for item in items:
            found = item
            num_matches += 1
            if num_matches > 1:  # raise exception not waiting
                                    # for the whole list walkthrough
                    raise exceptions.NoUniqueMatch

        if not found:
            msg = "No matching {0}".format(kwargs)
            raise exceptions.NotFound(msg)

        return found

    # depreciated
    def findall(self, **kwargs):
        _logger.warn(
            "The 'findall' methon was depreciated. Use 'list' instead")
        return [item for item in self.list(**kwargs) if _check_items(
            item,
            six.iteritems(kwargs))]


class CommonController(ReadOnlyController):
    """Common controller class used as a base class for controllers
    implementing method changing the data
    """

    def create(self, **kwargs):
        item = self.model(**kwargs)
        for (key, value) in kwargs.items():
            try:
                setattr(item, key, value)
            except warlock.InvalidOperation as e:
                raise TypeError(six.u(e))
        try:
            response = self.http_client.post(self.RESOURCE, data=item)
        except exceptions.ConnectionError:
            return None

        try:
            item = response.json()
        except ValueError:
            _logger.warning(
                "Invalid JSON format. Received: '{}'".format(response.text))
            return None

        return self.model(**item)

    def delete(self, item_id):
        url = '{0}?id={1}'.format(self.RESOURCE, item_id)
        self.http_client.delete(url)
        return

    def update(self, data):
        try:
            response = self.http_client.put(self.RESOURCE, json=data)
        except exceptions.ConnectionError:
            return None

        try:
            item = response.json()
        except ValueError:
            _logger.warning(
                "Invalid JSON format. Received: '{}'".format(response.text))
            _logger.warning(
                "Refer to: http://bugzilla.fibaro.com/view.php?id=1176")
            return None

        return self.model(**item)
