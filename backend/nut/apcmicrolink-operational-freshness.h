/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef APCMICROLINK_OPERATIONAL_FRESHNESS_H
#define APCMICROLINK_OPERATIONAL_FRESHNESS_H

#include "apcmicrolink-continuous.h"

typedef struct {
	uint32_t observed_fields;
	uint64_t last_successful_minimum_ms;
	uint64_t generation;
	int has_successful_minimum;
	int pending;
} mlink_operational_freshness_t;

/* Candidate fields are public for fixed-size stack allocation. Treat as opaque. */
typedef struct {
	const mlink_operational_freshness_t *owner;
	uint64_t generation;
	uint64_t proposed_minimum_ms;
	int valid;
} mlink_operational_freshness_candidate_t;

typedef enum {
	MLINK_FRESHNESS_ERROR = -1,
	MLINK_FRESHNESS_INELIGIBLE = 0,
	MLINK_FRESHNESS_ELIGIBLE = 1
} mlink_operational_freshness_result_t;

void mlink_operational_freshness_init(mlink_operational_freshness_t *state);

/*
 * Call only after the formatter has accepted a complete serialized-valid
 * schema-2 sample. elapsed_now_ms is monotonic time relative to stream start.
 * Prepare unions every observed nonstatic field, including on ineligible
 * samples. It never advances the successful-publication watermark.
 *
 * A successful candidate is valid only for this state and until its next
 * prepare or commit. Call commit only after publication succeeded and the
 * native guard confirmed the lease is still live. No clock, I/O, allocation,
 * locking, or lease renewal occurs here.
 */
mlink_operational_freshness_result_t mlink_operational_freshness_prepare(
	mlink_operational_freshness_t *state,
	const mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT],
	uint64_t elapsed_now_ms,
	mlink_operational_freshness_candidate_t *candidate);

/* Returns 1 only for the current eligible candidate; rejects replay/foreign/stale. */
int mlink_operational_freshness_commit(
	mlink_operational_freshness_t *state,
	mlink_operational_freshness_candidate_t *candidate);

#endif /* APCMICROLINK_OPERATIONAL_FRESHNESS_H */
