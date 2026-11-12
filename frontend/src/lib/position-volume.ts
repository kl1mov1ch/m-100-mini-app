import type { Position } from '../types';
import { nf, unit } from './format';

const workVolume = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 8 });

export function estimateBalance(
	position: Pick<Position, 'planned' | 'completed'>,
	previous: number | null | undefined,
	today: number | null | undefined,
) {
	const saved = previous ?? 0;
	const entered = today ?? 0;
	const delta = entered - saved;
	const balance = position.planned - position.completed;
	const remaining = balance - delta;
	return {
		planned: position.planned,
		available: Math.max(0, balance + saved),
		today: entered,
		completed: position.completed + delta,
		remaining: Math.max(0, remaining),
		excess: remaining < -1e-8 ? -remaining : 0,
	};
}

export function formatWorkVolume(value: number, measure: string) {
	return `${workVolume.format(value)} ${unit(measure)}`;
}

export function estimateStatus(values: Pick<Position, 'planned' | 'completed'>, unit: string) {
	const balance = values.planned - values.completed;
	return balance < -1e-8
		? `Перерасход на ${formatWorkVolume(-balance, unit)}`
		: `Остаток ${formatWorkVolume(Math.max(0, balance), unit)}`;
}

export function positionOverrun(position: Position) {
	const remote = position.bitrix;
	const fromBitrix = remote != null && remote.remaining <= position.remaining;
	const values = fromBitrix ? remote : position;
	return values.remaining < 0 ? { ...values, fromBitrix } : null;
}

export function formatVolume(value: number, measure: string) {
	return (value < 0 ? '−' : '') + nf.format(Math.abs(value)) + ' ' + unit(measure);
}
