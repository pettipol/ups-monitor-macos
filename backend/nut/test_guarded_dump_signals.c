/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic-only test harness for the guarded dump termination helper.
 * This file is not part of or linked into a NUT driver.
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "guarded_dump_signal_generated.c"

static int marker_fd = -1;

static void write_atexit_marker(void)
{
	const char marker = 'X';
	if (marker_fd >= 0) {
		(void)write(marker_fd, &marker, 1);
	}
}

static int wait_for_child(pid_t child, int *status)
{
	struct timespec pause_time = {0, 10000000};
	int attempt;

	for (attempt = 0; attempt < 200; attempt++) {
		pid_t result = waitpid(child, status, WNOHANG);
		if (result == child) {
			return 1;
		}
		if (result < 0 && errno != EINTR) {
			return 0;
		}
		(void)nanosleep(&pause_time, NULL);
	}

	/* This signal is sent only to the harness-owned synthetic child. */
	(void)kill(child, SIGKILL);
	while (waitpid(child, status, 0) < 0 && errno == EINTR) {
	}
	return 0;
}

static int run_case(int signal_number, int inherited_ignored)
{
	struct sigaction previous_action;
	struct sigaction ignored_action;
	int marker_pipe[2];
	int ready_pipe[2];
	int status = 0;
	int exited_before_timeout;
	char marker = '\0';
	ssize_t marker_count;
	pid_t child;

	if (sigaction(signal_number, NULL, &previous_action) != 0) {
		return 0;
	}
	if (inherited_ignored) {
		ignored_action.sa_handler = SIG_IGN;
		if (sigemptyset(&ignored_action.sa_mask) != 0) {
			return 0;
		}
		ignored_action.sa_flags = 0;
		if (sigaction(signal_number, &ignored_action, NULL) != 0) {
			return 0;
		}
	}
	if (pipe(marker_pipe) != 0) {
		(void)sigaction(signal_number, &previous_action, NULL);
		return 0;
	}
	if (pipe(ready_pipe) != 0) {
		close(marker_pipe[0]);
		close(marker_pipe[1]);
		(void)sigaction(signal_number, &previous_action, NULL);
		return 0;
	}

	child = fork();
	if (child == 0) {
		close(marker_pipe[0]);
		close(ready_pipe[0]);
		marker_fd = marker_pipe[1];
		if (atexit(write_atexit_marker) != 0 || setup_guarded_dump_signals() != 0) {
			_exit(90);
		}
		if (write(ready_pipe[1], "R", 1) != 1) {
			_exit(91);
		}
		close(ready_pipe[1]);
		{
			struct timespec deadline;
			struct timespec now;
			struct timespec pause_time = {0, 1000000};
			if (clock_gettime(CLOCK_MONOTONIC, &deadline) != 0) {
				_exit(92);
			}
			deadline.tv_sec += 5;
			while (guarded_dump_signal == 0) {
				if (clock_gettime(CLOCK_MONOTONIC, &now) != 0
					|| now.tv_sec > deadline.tv_sec
					|| (now.tv_sec == deadline.tv_sec && now.tv_nsec >= deadline.tv_nsec)) {
					exit(EXIT_FAILURE);
				}
				(void)nanosleep(&pause_time, NULL);
			}
			exit_if_guarded_dump_signal_requested();
		}
	}

	close(marker_pipe[1]);
	close(ready_pipe[1]);
	if (child < 0) {
		close(marker_pipe[0]);
		close(ready_pipe[0]);
		(void)sigaction(signal_number, &previous_action, NULL);
		return 0;
	}
	{
		struct pollfd ready_poll;
		char ready = '\0';
		ready_poll.fd = ready_pipe[0];
		ready_poll.events = POLLIN;
		ready_poll.revents = 0;
		if (poll(&ready_poll, 1, 2000) != 1
			|| !(ready_poll.revents & POLLIN)
			|| read(ready_pipe[0], &ready, 1) != 1
			|| ready != 'R') {
			(void)kill(child, SIGKILL);
			(void)waitpid(child, &status, 0);
			close(ready_pipe[0]);
			close(marker_pipe[0]);
			(void)sigaction(signal_number, &previous_action, NULL);
			return 0;
		}
	}
	close(ready_pipe[0]);
	if (kill(child, signal_number) != 0) {
		(void)kill(child, SIGKILL);
	}
	exited_before_timeout = wait_for_child(child, &status);
	marker_count = read(marker_pipe[0], &marker, 1);
	close(marker_pipe[0]);
	(void)sigaction(signal_number, &previous_action, NULL);

	return exited_before_timeout
		&& WIFEXITED(status)
		&& WEXITSTATUS(status) == EXIT_FAILURE
		&& marker_count == 1
		&& marker == 'X';
}

int main(void)
{
	static const int signals_to_test[] = {SIGTERM, SIGINT, SIGQUIT};
	static const char *const signal_names[] = {"SIGTERM", "SIGINT", "SIGQUIT"};
	unsigned int failures = 0;
	size_t index;

	for (index = 0; index < sizeof(signals_to_test) / sizeof(signals_to_test[0]); index++) {
		if (!run_case(signals_to_test[index], 0)) {
			printf("FAIL %s did not exit cooperatively with atexit\n", signal_names[index]);
			failures++;
		}
	}
	if (!run_case(SIGTERM, 1)) {
		printf("FAIL inherited ignored SIGTERM was not handled cooperatively\n");
		failures++;
	}
	if (failures != 0) {
		printf("%u synthetic termination check(s) failed\n", failures);
		return 1;
	}
	printf("all guarded dump signal validation checks passed\n");
	return 0;
}
