import assert from 'node:assert/strict';
import { calculateAmount } from '../frontend/src/lib/calculation.ts';
assert.equal(calculateAmount([{ quantity: 1, rate: 1.005 }]), 1.01);
assert.equal(calculateAmount([{ quantity: 0.1, rate: 0.2 }]), 0.02);
assert.equal(
	calculateAmount([
		{ quantity: 15, rate: 10 },
		{ quantity: 15, rate: 10 },
		{ quantity: 15, rate: 2 },
		{ quantity: 15, rate: 2 },
		{ quantity: 56, rate: 2 },
		{ quantity: 10, rate: 0 },
	]),
	472,
);
assert.equal(
	calculateAmount([
		{ quantity: 3, rate: 0.335 },
		{ quantity: 1, rate: 0.005 },
	]),
	1.01,
);
process.stdout.write('Money calculations passed\n');
