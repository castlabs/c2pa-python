# Copyright 2025 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

try:
    from importlib.metadata import version
    __version__ = version("c2pa-python")
except ImportError:  # pragma: no cover
    __version__ = "unknown"

from .c2pa import (
    Builder,
    C2paError,
    Reader,
    C2paSigningAlg,
    C2paDigitalSourceType,
    C2paBuilderIntent,
    C2paSignerInfo,
    Signer,
    Stream,
    Settings,
    Context,
    ContextBuilder,
    ContextProvider,
    LiveVideoVsiSession,
    TrustedVsiPrehashedSession,
    VsiSigningContextV1,
    TrustedVsiInitUuidReservation,
    TrustedVsiMediaEmsgReservation,
    TrustedVsiStatus,
    has_dynamic_assertions,
    has_fragmented_files,
    has_live_video_vsi,
    has_live_video_vsi_callbacks,
    has_live_video_vsi_explicit_time,
    has_live_video_vsi_mfhd_probe,
    has_live_video_vsi_recovery,
    has_live_video_trusted_vsi_split_init,
    has_live_video_trusted_vsi_expert_emsg,
    has_live_video_trusted_vsi_composed_emsg,
    has_live_video_trusted_vsi_recovery,
    has_live_video_trusted_vsi_signing_context_v1,
    has_live_video_trusted_vsi_full_uint32_exhaustion,
    moof_sequence_number,
    sdk_version,
    load_settings
)  # NOQA

# Re-export C2paError and its subclasses
__all__ = [
    'Builder',
    'C2paError',
    'Reader',
    'C2paSigningAlg',
    'C2paDigitalSourceType',
    'C2paBuilderIntent',
    'C2paSignerInfo',
    'Signer',
    'Stream',
    'Settings',
    'Context',
    'ContextBuilder',
    'ContextProvider',
    'LiveVideoVsiSession',
    'TrustedVsiPrehashedSession',
    'VsiSigningContextV1',
    'TrustedVsiInitUuidReservation',
    'TrustedVsiMediaEmsgReservation',
    'TrustedVsiStatus',
    'has_dynamic_assertions',
    'has_fragmented_files',
    'has_live_video_vsi',
    'has_live_video_vsi_callbacks',
    'has_live_video_vsi_explicit_time',
    'has_live_video_vsi_mfhd_probe',
    'has_live_video_vsi_recovery',
    'has_live_video_trusted_vsi_split_init',
    'has_live_video_trusted_vsi_expert_emsg',
    'has_live_video_trusted_vsi_composed_emsg',
    'has_live_video_trusted_vsi_recovery',
    'has_live_video_trusted_vsi_signing_context_v1',
    'has_live_video_trusted_vsi_full_uint32_exhaustion',
    'moof_sequence_number',
    'sdk_version',
    'load_settings'
]
