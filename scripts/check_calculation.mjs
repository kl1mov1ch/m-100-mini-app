import assert from 'node:assert/strict';
import { calculateAmount, mergeWorkQuantities } from '../frontend/src/lib/calculation.ts';
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
assert.deepEqual(mergeWorkQuantities([{item_id:'copper',quantity:15},{item_id:'cable',quantity:8},{item_id:'copper',quantity:5}]),[{item_id:'copper',quantity:20},{item_id:'cable',quantity:8}]);
assert.deepEqual(mergeWorkQuantities([{item_id:'work',quantity:0.1},{item_id:'work',quantity:0.2}]),[{item_id:'work',quantity:0.3}]);
assert.deepEqual(mergeWorkQuantities([{item_id:'work',quantity:0.00000001},{item_id:'work',quantity:0.00000002}]),[{item_id:'work',quantity:0.00000003}]);
assert.throws(()=>mergeWorkQuantities([{item_id:'work',quantity:NaN}]));
assert.throws(()=>mergeWorkQuantities([{item_id:'work',quantity:-1}]));
process.stdout.write('Report quantities merge without duplicate work rows or decimal drift\n');
