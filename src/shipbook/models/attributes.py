from typing import Union

# The app's own key/values on a job's session or a request's start event: primitives only,
# so they list and index flat.
Attributes = dict[str, Union[str, int, float, bool]]
