#!/usr/bin/python
#
# config.py
#
# Copyright (c) 2023, Paul Holleis, Marko Luther
# All rights reserved.
#
#
# ABOUT
# This module connects to the artisan.plus inventory management service

# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later version. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from typing import Final, TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow # pylint: disable=unused-import

# Constants
# Internal service identifier — also used as the OS keyring service name under which
# cloud credentials are stored (see get_keyring_service_name). Kept stable for backward
# compatibility: changing it would orphan already-saved logins and force users to re-login.
app_name: Final[str] = 'artisan.plus'
# User-facing name of the cloud service shown in the UI (login/schedule/upload messages).
app_display_name: Final[str] = 'RoastArtisan'
profile_ext: Final[str] = 'alog'
uuid_tag: Final[str] = 'roastUUID' # as used in .alog profiles, send as 'roast_id' as part of the sync record to the server
schedule_uuid_tag: Final[str] = 'scheduleID' # send as 's_item_id' as part of the sync record to the server
schedule_date_tag: Final[str] = 'scheduleDate' # send as 's_item_date' as part of the sync record to the server

# Service URLs

# # LOCAL SETUP
#api_base_url         = 'https://localhost:62602/api/v1'
#web_base_url         = 'https://localhost:8088'

# # CLOUD SETUP
default_api_base_url: Final[str] = 'https://artisan.plus/api/v1'
default_web_base_url: Final[str] = 'https://artisan.plus'
default_shop_base_url: Final[str] = 'https://buy.artisan.plus/'

api_base_url: str
web_base_url: str
shop_base_url: str

register_url: str
reset_passwd_url: str
auth_url: str
stock_url: str
roast_url: str
lock_schedule_url: str
notifications_url: str
profile_upload_url_template: str
profile_data_url_template: str
references_url: str
reference_detail_url_template: str

# Connection configurations

#verify_ssl: Final[bool] = False
verify_ssl: Final[bool] = True
connect_timeout: Final[int] = 6  # in seconds
read_timeout: Final[int] = 12  # in seconds
read_timeout_max: Final[int] = 30  # in seconds
min_passwd_len: Final[int] = 4
min_login_len: Final[int] = 6
compress_posts: Final[bool] = True
# post_compression_threshold holds the number in bytes before compression
# kicks in
# (data smaller than this are always send uncompressed via POST)
post_compression_threshold: Final[int] = 500

# Authentication configuration

# do not authentify successfully after max_days after the subscription expired
expired_subscription_max_days: Final[int] = 90

# Cache and queue parameters

# Note: stock_cache_expiration should be larger than schedule_cache_expiration
stock_cache_expiration: Final[int] = 35   # expiration period in seconds for full stock updates (expensive)
schedule_cache_expiration: Final[int] = 5 # expiration period in seconds for full stock updates only in case the schedule on the server has changed

queue_start_delay: Final[int] = 5  # startup time of queue in seconds
# delay between tasks in seconds (cycling interval of the queue)
queue_task_delay: Final[float] = 2.0
queue_retries: Final[int] = 2  # number of retries (should be >=0)
queue_retry_delay: Final[int] = 30  # time between retries in seconds
queue_discard_after: Final[int] = 3*24*60*60 # period in seconds after 'modified_at'..
# .. until a queued item is removed from the queue; if queue_discard_after is 0 items are never discarded
# queque_put_timeout indicates the number of seconds to wait on putting
# a new item into the queue (unused for now)
queue_put_timeout: Final[float] = 0.5


# AppData

# the stock cache reflects the current coffee stock of the account and
# gets automatically synced with the cloud
stock_cache: Final[str] = 'cache'

# the completed roasts cache reflects the last roasted scheduled items
completed_roasts_cache: Final[str] = 'completed'

# the prepared items cache reflects the prepared scheduled items
prepared_items_cache: Final[str] = 'prepared'

# the hidden items cache reflects the hidden scheduled items
hidden_items_cache: Final[str] = 'hidden'

# the uuid register that associates UUIDs with local filepaths where to
# locate the corresponding Artisan profiles
uuid_cache: Final[str] = 'uuids'

# the account register that associates account ids with a local running
# account number
# Note: the account_cache file is shared between the main Artisan and the
# ArtisanViewer app, protected by a filelock
account_cache: Final[str] = 'account'

# the account nr locally associated to the current account, or None
account_nr: int|None = None

# the sync register that associates UUIDs with last known modification dates
# modified_at for profiles uploaded/synced automatically
# Note: the sync_cache file is shared between the main Artisan and the
# ArtisanViewer app, protected by a filelock
sync_cache: Final[str] = 'sync'

# the outbox queues the outgoing PUSH/PUT data requests
# Note: the outbox_cache file is shared between the main Artisan and the
# ArtisanViewer app, NOT protected by an extra filelock
outbox_cache: Final[str] = 'outbox'


# Runtime variables

app_window: 'ApplicationWindow|None' = None  # handle to the main Artisan application window
#   if set, app_window.plus_login holds the current login account if any and
#   app_window.updatePlusIcon() is a function that updates the toolbar
#   plus service connection indicator icon
connected: bool = False  # connection status
passwd: str|None = None
# the session token
token: str|None = None
# login nickname assigned on login with session token
nickname: str|None = None

# configured server base URL persisted in app settings
server_url: str = default_web_base_url


def normalize_server_url(url: str|None) -> str:
    candidate = (url or '').strip()
    if candidate == '':
        return default_web_base_url
    if '://' not in candidate:
        host = candidate.split('/', 1)[0].lower()
        if host in {'localhost', '127.0.0.1', '::1'} or host.startswith(('localhost:', '127.0.0.1:', '[::1]:')):
            candidate = f'http://{candidate}'
        else:
            candidate = f'https://{candidate}'
    parsed = urlsplit(candidate)
    netloc = parsed.netloc if parsed.netloc else parsed.path
    path = parsed.path if parsed.netloc else ''
    normalized = urlunsplit((parsed.scheme or 'https', netloc, path.rstrip('/'), '', ''))
    return normalized.rstrip('/')


def derive_service_base_urls(url: str|None) -> tuple[str, str]:
    normalized = normalize_server_url(url)
    parsed = urlsplit(normalized)
    path = parsed.path.rstrip('/')
    if path.endswith('/api/v1'):
        web_path = path[:-len('/api/v1')]
        api_path = path
    else:
        web_path = path
        api_path = f'{path}/api/v1' if path else '/api/v1'
    web = urlunsplit((parsed.scheme, parsed.netloc, web_path, '', '')).rstrip('/')
    api = urlunsplit((parsed.scheme, parsed.netloc, api_path, '', '')).rstrip('/')
    return web, api


def set_server_base_url(url: str|None) -> None:
    global server_url, web_base_url, api_base_url, shop_base_url
    global register_url, reset_passwd_url, auth_url, stock_url, roast_url, lock_schedule_url, notifications_url, profile_upload_url_template, profile_data_url_template, references_url, reference_detail_url_template

    web_base_url, api_base_url = derive_service_base_urls(url)
    server_url = web_base_url
    if web_base_url == default_web_base_url:
        shop_base_url = default_shop_base_url
    else:
        shop_base_url = web_base_url

    register_url = web_base_url + '/register'
    reset_passwd_url = web_base_url + '/resetPassword'
    auth_url = api_base_url + '/accounts/users/authenticate'
    stock_url = api_base_url + '/acoffees'
    roast_url = api_base_url + '/aroast'
    lock_schedule_url = api_base_url + '/aschedule/lock'
    notifications_url = api_base_url + '/notifications'
    profile_upload_url_template = api_base_url + '/roasts/{roast_id}/upload-profile'
    profile_data_url_template = api_base_url + '/roasts/{roast_id}/profile/data'
    references_url = api_base_url + '/roasts/references'
    # NOTE: route inferred from the comments endpoint /roasts/{roast_id}/reference/comments;
    # confirm against the cloud reference-detail endpoint (cloud-side dependency).
    reference_detail_url_template = api_base_url + '/roasts/{roast_id}/reference'


def get_keyring_service_name() -> str:
    if server_url == default_web_base_url:
        return app_name
    return f'{app_name}@{server_url}'


def profile_upload_enabled() -> bool:
    return server_url != default_web_base_url


def remote_profile_fetch_enabled() -> bool:
    return server_url != default_web_base_url


def get_profile_upload_url(roast_id: str) -> str:
    return profile_upload_url_template.format(roast_id=roast_id)


def get_profile_data_url(roast_id: str) -> str:
    return profile_data_url_template.format(roast_id=roast_id)


set_server_base_url(default_web_base_url)
