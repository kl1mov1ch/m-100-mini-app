type WorkValue = { quantity: number | null; rate: number };

function decimalValue(value: number): { integer: bigint; scale: number } {
	const [coefficient, exponentText = '0'] = String(value).toLowerCase().split('e');
	const [whole, fraction = ''] = coefficient.split('.');
	const scale = fraction.length - Number(exponentText);
	const integer = BigInt(whole + fraction);
	return scale < 0 ? { integer: integer * 10n ** BigInt(-scale), scale: 0 } : { integer, scale };
}

export function calculateAmount(works: WorkValue[]): number {
	let total = 0n;
	let totalScale = 0;
	for (const work of works) {
		const quantity = decimalValue(work.quantity || 0);
		const rate = decimalValue(work.rate);
		const scale = quantity.scale + rate.scale;
		if (scale > totalScale) {
			total *= 10n ** BigInt(scale - totalScale);
			totalScale = scale;
		}
		total += quantity.integer * rate.integer * 10n ** BigInt(totalScale - scale);
	}
	if (totalScale < 2) return Number(total * 10n ** BigInt(2 - totalScale)) / 100;
	const denominator = 10n ** BigInt(totalScale - 2);
	const sign = total < 0n ? -1n : 1n;
	const magnitude = total * sign;
	return Number(sign * ((magnitude + denominator / 2n) / denominator)) / 100;
}
