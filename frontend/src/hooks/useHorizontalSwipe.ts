import { useRef, type MouseEvent, type TouchEvent } from 'react';

export function useHorizontalSwipe(onSwipe: (step: -1 | 1) => void, disabled = false) {
	const start = useRef<{ id: number; x: number; y: number } | null>(null);
	const suppressClickUntil = useRef(0);

	const onTouchStart = (event: TouchEvent<HTMLElement>) => {
		start.current = null;
		suppressClickUntil.current = 0;
		if (disabled || event.touches.length !== 1) return;
		const target = event.target;
		if (
			!(target instanceof Element) ||
			!event.currentTarget.contains(target) ||
			target.closest(
				'input, textarea, select, [contenteditable], [role="combobox"], [role="slider"], [role="switch"], [data-no-swipe]',
			)
		)
			return;
		const touch = event.touches[0];
		if (touch.clientX < 24 || touch.clientX > window.innerWidth - 24) return;
		start.current = { id: touch.identifier, x: touch.clientX, y: touch.clientY };
	};
	const onTouchEnd = (event: TouchEvent<HTMLElement>) => {
		const initial = start.current;
		start.current = null;
		if (disabled || !initial || event.touches.length) return;
		const touch = Array.from(event.changedTouches).find((entry) => entry.identifier === initial.id);
		if (!touch) return;
		const horizontal = touch.clientX - initial.x;
		const vertical = touch.clientY - initial.y;
		if (Math.abs(horizontal) < 50 || Math.abs(horizontal) < Math.abs(vertical) * 1.5) return;
		event.stopPropagation();
		suppressClickUntil.current = Date.now() + 400;
		onSwipe(horizontal < 0 ? 1 : -1);
	};
	const onClickCapture = (event: MouseEvent<HTMLElement>) => {
		if (event.detail && Date.now() < suppressClickUntil.current) {
			event.preventDefault();
			event.stopPropagation();
		}
	};
	return {
		onTouchStart,
		onTouchEnd,
		onTouchCancel: () => {
			start.current = null;
		},
		onClickCapture,
	};
}
