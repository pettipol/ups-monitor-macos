/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "apcmicrolink-operational-freshness.h"

#include <string.h>

#define MLINK_FRESHNESS_STATUS_INDEX 0U
#define MLINK_FRESHNESS_STATIC_FIRST 13U
#define MLINK_FRESHNESS_STATIC_LAST 14U
#define MLINK_FRESHNESS_MAX_STATUS_AGE_MS UINT64_C(10000)

static int
is_static_index(size_t index)
{
	return index >= MLINK_FRESHNESS_STATIC_FIRST && index <= MLINK_FRESHNESS_STATIC_LAST;
}

void
mlink_operational_freshness_init(mlink_operational_freshness_t *state)
{
	if (state != NULL)
		memset(state, 0, sizeof(*state));
}

mlink_operational_freshness_result_t
mlink_operational_freshness_prepare(
	mlink_operational_freshness_t *state,
	const mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT],
	uint64_t elapsed_now_ms,
	mlink_operational_freshness_candidate_t *candidate)
{
	uint32_t current_fields = 0U;
	uint64_t minimum = MLINK_OPERATIONAL_MAX_SAFE_INTEGER;
	int have_minimum = 0;
	const mlink_operational_field_t *status;
	size_t index;
	int status_fresh;
	int no_shrink;
	int advances;

	/* Any attempted successor revokes the prior publication authorization. */
	if (state != NULL)
		state->pending = 0;
	if (candidate != NULL)
		memset(candidate, 0, sizeof(*candidate));
	if (state == NULL || fields == NULL || candidate == NULL
		|| elapsed_now_ms > MLINK_OPERATIONAL_MAX_SAFE_INTEGER
		|| state->generation == MLINK_OPERATIONAL_MAX_SAFE_INTEGER)
		return MLINK_FRESHNESS_ERROR;
	for (index = 0U; index < MLINK_CONTINUOUS_FIELD_COUNT; index++) {
		const mlink_operational_field_t *field = &fields[index];
		if (field->state != MLINK_CONTINUOUS_OBSERVED
			&& field->state != MLINK_CONTINUOUS_UNAVAILABLE
			&& field->state != MLINK_CONTINUOUS_INVALID)
			return MLINK_FRESHNESS_ERROR;
		if (field->state != MLINK_CONTINUOUS_OBSERVED || is_static_index(index))
			continue;
		if (!field->has_time || field->observed_ms > MLINK_OPERATIONAL_MAX_SAFE_INTEGER)
			return MLINK_FRESHNESS_ERROR;
		current_fields |= (uint32_t)1U << index;
		if (!have_minimum || field->observed_ms < minimum) {
			minimum = field->observed_ms;
			have_minimum = 1;
		}
	}

	/* Successful formatter validation guarantees static classification and shapes. */
	state->observed_fields |= current_fields;
	state->generation++;
	state->pending = 0;

	status = &fields[MLINK_FRESHNESS_STATUS_INDEX];
	status_fresh = status->state == MLINK_CONTINUOUS_OBSERVED
		&& !is_static_index(MLINK_FRESHNESS_STATUS_INDEX)
		&& status->has_time
		&& status->observed_ms <= elapsed_now_ms
		&& elapsed_now_ms - status->observed_ms <= MLINK_FRESHNESS_MAX_STATUS_AGE_MS;
	no_shrink = (state->observed_fields & current_fields) == state->observed_fields;
	advances = have_minimum && (!state->has_successful_minimum
		|| minimum > state->last_successful_minimum_ms);
	if (!status_fresh || !have_minimum || !no_shrink || !advances)
		return MLINK_FRESHNESS_INELIGIBLE;

	state->pending = 1;
	candidate->owner = state;
	candidate->generation = state->generation;
	candidate->proposed_minimum_ms = minimum;
	candidate->valid = 1;
	return MLINK_FRESHNESS_ELIGIBLE;
}

int
mlink_operational_freshness_commit(
	mlink_operational_freshness_t *state,
	mlink_operational_freshness_candidate_t *candidate)
{
	if (state == NULL || candidate == NULL || !candidate->valid
		|| candidate->owner != state || !state->pending
		|| candidate->generation != state->generation
		|| candidate->proposed_minimum_ms > MLINK_OPERATIONAL_MAX_SAFE_INTEGER
		|| (state->has_successful_minimum
			&& candidate->proposed_minimum_ms <= state->last_successful_minimum_ms))
		return 0;

	state->last_successful_minimum_ms = candidate->proposed_minimum_ms;
	state->has_successful_minimum = 1;
	state->pending = 0;
	candidate->valid = 0;
	return 1;
}
