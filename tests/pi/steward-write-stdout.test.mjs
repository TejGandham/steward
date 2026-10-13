// The print-mode writer behind /steward-models: retries a refusing pipe with a short
// blocking sleep, and on give-up says so on stderr instead of dropping output silently.
import { test } from "node:test";
import assert from "node:assert/strict";

import { writeAllSync } from "../../pi/extensions/steward/index.ts";

function eagain() {
	return Object.assign(new Error("EAGAIN: resource temporarily unavailable"), { code: "EAGAIN" });
}

test("retries EAGAIN with a sleep between tries and writes everything", () => {
	const out = [];
	const sleeps = [];
	let refusals = 3;
	const write = (buf, off, len) => {
		if (refusals-- > 0) throw eagain();
		const n = Math.min(4, len); // short writes too
		out.push(buf.subarray(off, off + n).toString("utf8"));
		return n;
	};
	const notices = [];
	writeAllSync("hello world\n", { write, sleep: (ms) => sleeps.push(ms), notice: (t) => notices.push(t) });
	assert.equal(out.join(""), "hello world\n");
	assert.equal(sleeps.length, 3);
	assert.ok(sleeps.every((ms) => ms > 0));
	assert.deepEqual(notices, []);
});

test("gives up after the retry budget with a one-line notice", () => {
	let calls = 0;
	const sleeps = [];
	const notices = [];
	const write = (buf, off, len) => {
		calls++;
		if (calls === 1) return 3; // part of it goes out
		throw eagain();
	};
	writeAllSync("abcdefgh", { write, sleep: (ms) => sleeps.push(ms), notice: (t) => notices.push(t), maxTries: 5 });
	assert.equal(sleeps.length, 5);
	assert.equal(notices.length, 1);
	assert.match(notices[0], /^steward: .*5 of 8 bytes.*\n$/);
	assert.equal(notices[0].trimEnd().split("\n").length, 1);
});

test("another write error stops at once with a notice", () => {
	const notices = [];
	const sleeps = [];
	const write = () => {
		throw Object.assign(new Error("EPIPE"), { code: "EPIPE" });
	};
	writeAllSync("abc", { write, sleep: (ms) => sleeps.push(ms), notice: (t) => notices.push(t) });
	assert.equal(sleeps.length, 0);
	assert.equal(notices.length, 1);
	assert.match(notices[0], /EPIPE/);
});
