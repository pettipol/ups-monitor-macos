/* SPDX-License-Identifier: GPL-2.0-or-later
 * Explicit, unregistered HIDAPI 0.15.0 host binding. No device operations are
 * performed by create/dispose except hid_exit during initialized disposal.
 */
#ifndef APCMICROLINK_HIDAPI_NATIVE_H
#define APCMICROLINK_HIDAPI_NATIVE_H

#include "apcmicrolink-hidapi-shared-host.h"

typedef struct mlink_hidapi_native_config {
	unsigned short vendor_id;
	unsigned short product_id;
	int (*stop_requested)(void *user);
	void *stop_user;
} mlink_hidapi_native_config_t;

typedef struct mlink_hidapi_native_binding {
	const mlink_shared_host_ops_t *ops;
	void *user;
} mlink_hidapi_native_binding_t;

/* Single owner, single calling thread, isolated process; no concurrent HIDAPI
 * users. Outputs must initially be {0}. Creation allocates only local memory.
 * Use only with the guarded core; this API does not register or activate it. */
int mlink_hidapi_native_create(const mlink_hidapi_native_config_t *config,
	mlink_hidapi_native_binding_t *binding);

/* Never auto-closes. Refuses an owned handle or an active callback. Only after
 * close has returned may this release HIDAPI globals with hid_exit and free.
 * A failed hid_exit retains ownership. Success zeroes the caller's bundle. */
int mlink_hidapi_native_dispose(mlink_hidapi_native_binding_t *binding);

#endif
