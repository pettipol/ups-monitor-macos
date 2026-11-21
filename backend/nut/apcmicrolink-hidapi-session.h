/* SPDX-License-Identifier: GPL-2.0-or-later
 * One-shot production session gate for the unregistered HIDAPI candidate.
 */
#ifndef APCMICROLINK_HIDAPI_SESSION_H
#define APCMICROLINK_HIDAPI_SESSION_H

#include "apcmicrolink-hidapi-shared-host.h"

#if defined(MLINK_HIDAPI_NATIVE_CANDIDATE) && defined(MLINK_HIDAPI_SHARED_TEST)
#error "MLINK_HIDAPI_NATIVE_CANDIDATE and MLINK_HIDAPI_SHARED_TEST are mutually exclusive"
#endif

#ifdef MLINK_HIDAPI_NATIVE_CANDIDATE
struct mlink_hidapi_native_config;

typedef enum mlink_hidapi_session_finish {
	MLINK_HIDAPI_SESSION_RELEASED = 0,
	MLINK_HIDAPI_SESSION_RETAINED = 1
} mlink_hidapi_session_finish_t;

/* Consumes the process's sole preparation attempt, creates only the native
 * local binding, and starts a nonrenewable guard. It performs no HID calls. */
int mlink_shared_prepare_native(
	const struct mlink_hidapi_native_config *config, long seconds);

/* Marks terminal and releases only after close and callbacks are quiescent.
 * May be requested reentrantly; no subsequent I/O is admitted. RETAINED means
 * ownership remains; a failed close/dispose is never automatically retried. */
mlink_hidapi_session_finish_t mlink_shared_finish_native(void);
#endif

#endif
