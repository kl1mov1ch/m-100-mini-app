import type { Position } from '../types';
import { nf, unit } from './format';

export function positionOverrun(position: Position) {
	const remote = position.bitrix;
	const fromBitrix = remote != null && remote.remaining <= position.remaining;
	const values = fromBitrix ? remote : position;
	return values.remaining < 0 ? { ...values, fromBitrix } : null;
}

export function formatVolume(value: number, measure: string) {
	return (value < 0 ? '−' : '') + nf.format(Math.abs(value)) + ' ' + unit(measure);
}
