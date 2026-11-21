/* Synthetic tests for the bounded operational freshness helper. */
#include "apcmicrolink-operational-freshness.h"

#include <assert.h>
#include <stdint.h>
#include <string.h>

static void
fields_reset(mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT])
{
	size_t index;
	memset(fields, 0, sizeof(mlink_operational_field_t) * MLINK_CONTINUOUS_FIELD_COUNT);
	for (index = 0U; index < MLINK_CONTINUOUS_FIELD_COUNT; index++) {
		fields[index].kind = index == 13U || index == 14U
			? MLINK_CONTINUOUS_STATIC
			: (index == 15U || index == 16U
				? MLINK_CONTINUOUS_DRIVER_DERIVED : MLINK_CONTINUOUS_REPORTED);
		fields[index].state = MLINK_CONTINUOUS_UNAVAILABLE;
	}
}

static void
observe(mlink_operational_field_t *field, uint64_t timestamp)
{
	(void)strcpy(field->value, "1");
	field->state = MLINK_CONTINUOUS_OBSERVED;
	field->has_value = 1;
	field->has_time = 1;
	field->observed_ms = timestamp;
}

static void
base_sample(mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT],
	uint64_t timestamp)
{
	fields_reset(fields);
	(void)strcpy(fields[0].value, "OL");
	fields[0].state = MLINK_CONTINUOUS_OBSERVED;
	fields[0].has_value = 1;
	fields[0].has_time = 1;
	fields[0].observed_ms = timestamp;
	observe(&fields[1], timestamp);
}

int
main(void)
{
	mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT];
	mlink_operational_freshness_t state, other;
	mlink_operational_freshness_candidate_t candidate, replay, foreign;
	uint64_t large = UINT64_C(4294967296) + UINT64_C(20000);

	/* >2^32 and publication watermark moves only on explicit commit. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, large);
	assert(mlink_operational_freshness_prepare(&state, fields, large, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(!state.has_successful_minimum);
	assert(mlink_operational_freshness_commit(&state, &candidate));
	assert(state.last_successful_minimum_ms == large);
	assert(!mlink_operational_freshness_commit(&state, &candidate)); /* duplicate */
	assert(mlink_operational_freshness_prepare(&state, fields, large, &candidate)
		== MLINK_FRESHNESS_INELIGIBLE); /* minimum must strictly advance */

	/* Out-of-range supplied fields are errors, not stale/ineligible samples. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 10U);
	fields[1].observed_ms = MLINK_OPERATIONAL_MAX_SAFE_INTEGER + UINT64_C(1);
	assert(mlink_operational_freshness_prepare(&state, fields, 10U, &candidate)
		== MLINK_FRESHNESS_ERROR);
	assert(state.observed_fields == 0U);

	/* A bounds error from the next prepare revokes the previous token. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 20U);
	assert(mlink_operational_freshness_prepare(&state, fields, 20U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(mlink_operational_freshness_prepare(&state, fields,
		MLINK_OPERATIONAL_MAX_SAFE_INTEGER + UINT64_C(1), &replay)
		== MLINK_FRESHNESS_ERROR);
	assert(!replay.valid);
	assert(!mlink_operational_freshness_commit(&state, &candidate));
	assert(!state.has_successful_minimum && state.last_successful_minimum_ms == 0U);

	/* Null field input revokes the prior token without changing the watermark. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 21U);
	assert(mlink_operational_freshness_prepare(&state, fields, 21U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(mlink_operational_freshness_prepare(&state, NULL, 21U, &replay)
		== MLINK_FRESHNESS_ERROR);
	assert(!replay.valid);
	assert(!mlink_operational_freshness_commit(&state, &candidate));
	assert(!state.has_successful_minimum);

	/* A null output candidate still revokes any previously pending token. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 22U);
	assert(mlink_operational_freshness_prepare(&state, fields, 22U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(mlink_operational_freshness_prepare(&state, fields, 23U, NULL)
		== MLINK_FRESHNESS_ERROR);
	assert(!mlink_operational_freshness_commit(&state, &candidate));
	assert(!state.has_successful_minimum);

	/* Generation exhaustion revokes the old pending token without wrapping. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 24U);
	assert(mlink_operational_freshness_prepare(&state, fields, 24U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	state.generation = MLINK_OPERATIONAL_MAX_SAFE_INTEGER;
	assert(mlink_operational_freshness_prepare(&state, fields, 25U, &replay)
		== MLINK_FRESHNESS_ERROR);
	assert(!replay.valid);
	assert(!mlink_operational_freshness_commit(&state, &candidate));
	assert(!state.has_successful_minimum);

	/* A field-validation error also revokes the previous token. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 30U);
	assert(mlink_operational_freshness_prepare(&state, fields, 30U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	fields[3].state = (mlink_continuous_state_t)99;
	assert(mlink_operational_freshness_prepare(&state, fields, 31U, &replay)
		== MLINK_FRESHNESS_ERROR);
	assert(!replay.valid);
	assert(!mlink_operational_freshness_commit(&state, &candidate));
	assert(!state.has_successful_minimum && state.last_successful_minimum_ms == 0U);

	/* A timestamp-range error revokes the prior token before returning. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 32U);
	assert(mlink_operational_freshness_prepare(&state, fields, 32U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	fields[4].state = MLINK_CONTINUOUS_OBSERVED;
	fields[4].has_time = 1;
	fields[4].observed_ms = MLINK_OPERATIONAL_MAX_SAFE_INTEGER + UINT64_C(1);
	assert(mlink_operational_freshness_prepare(&state, fields, 33U, &replay)
		== MLINK_FRESHNESS_ERROR);
	assert(!replay.valid);
	assert(!mlink_operational_freshness_commit(&state, &candidate));
	assert(!state.has_successful_minimum && state.last_successful_minimum_ms == 0U);

	/* Max-safe timestamp, elapsed edge, and checked generation exhaustion. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, MLINK_OPERATIONAL_MAX_SAFE_INTEGER);
	assert(mlink_operational_freshness_prepare(&state, fields,
		MLINK_OPERATIONAL_MAX_SAFE_INTEGER, &candidate) == MLINK_FRESHNESS_ELIGIBLE);
	mlink_operational_freshness_init(&state);
	state.generation = MLINK_OPERATIONAL_MAX_SAFE_INTEGER;
	assert(mlink_operational_freshness_prepare(&state, fields,
		MLINK_OPERATIONAL_MAX_SAFE_INTEGER, &candidate) == MLINK_FRESHNESS_ERROR);

	/* Status age is inclusive at 10,000 ms and stale at 10,001 ms. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 10U);
	assert(mlink_operational_freshness_prepare(&state, fields, 10010U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	mlink_operational_freshness_init(&state);
	base_sample(fields, 10U);
	observe(&fields[2], 20U);
	assert(mlink_operational_freshness_prepare(&state, fields, 10011U, &candidate)
		== MLINK_FRESHNESS_INELIGIBLE);
	assert((state.observed_fields & ((uint32_t)1U << 2U)) != 0U); /* union on stale */

	/* Static-only data never establishes dynamic progress. */
	mlink_operational_freshness_init(&state);
	fields_reset(fields);
	observe(&fields[13], 50U);
	observe(&fields[14], 50U);
	assert(mlink_operational_freshness_prepare(&state, fields, 50U, &candidate)
		== MLINK_FRESHNESS_INELIGIBLE);
	assert(state.observed_fields == 0U);

	/* Shrinking observed fields blocks eligibility, while retaining the union. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 100U);
	assert(mlink_operational_freshness_prepare(&state, fields, 100U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(mlink_operational_freshness_commit(&state, &candidate));
	fields_reset(fields);
	observe(&fields[0], 200U);
	assert(mlink_operational_freshness_prepare(&state, fields, 200U, &candidate)
		== MLINK_FRESHNESS_INELIGIBLE);
	assert((state.observed_fields & ((uint32_t)1U << 1U)) != 0U);

	/* Without commit after failed publication, the watermark remains unchanged. */
	mlink_operational_freshness_init(&state);
	base_sample(fields, 300U);
	assert(mlink_operational_freshness_prepare(&state, fields, 300U, &candidate)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(!state.has_successful_minimum); /* publication failure: omit commit */
	assert(mlink_operational_freshness_prepare(&state, fields, 301U, &replay)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(!mlink_operational_freshness_commit(&state, &candidate)); /* stale token */
	mlink_operational_freshness_init(&other);
	assert(mlink_operational_freshness_prepare(&other, fields, 301U, &foreign)
		== MLINK_FRESHNESS_ELIGIBLE);
	assert(!mlink_operational_freshness_commit(&state, &foreign));
	assert(mlink_operational_freshness_commit(&state, &replay));
	assert(!mlink_operational_freshness_commit(&state, &replay)); /* replay */

	return 0;
}
