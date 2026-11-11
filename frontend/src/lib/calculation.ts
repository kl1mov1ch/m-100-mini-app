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

export function mergeWorkQuantities(lines: { item_id: string; quantity: number }[]) {
	const quantities = new Map<string, { integer: bigint; scale: number }>();
	for (const line of lines) {
		if (!Number.isFinite(line.quantity) || line.quantity < 0)
			throw new Error('Проверьте объём работы');
		const next = decimalValue(line.quantity);
		const previous = quantities.get(line.item_id) || { integer: 0n, scale: 0 };
		const scale = Math.max(next.scale, previous.scale);
		quantities.set(line.item_id, {
			integer:
				previous.integer * 10n ** BigInt(scale - previous.scale) +
				next.integer * 10n ** BigInt(scale - next.scale),
			scale,
		});
	}
	return [...quantities].map(([item_id, value]) => ({
		item_id,
		quantity: Number(value.integer) / 10 ** value.scale,
	}));
}
