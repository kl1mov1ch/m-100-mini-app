export function inputScrollDistance(
	top: number,
	bottom: number,
	visibleTop: number,
	visibleBottom: number,
): number {
	const margin = 20;
	const available = visibleBottom - visibleTop - margin * 2;
	if (bottom - top > available) return top - visibleTop - margin;
	if (bottom > visibleBottom - margin) return bottom - visibleBottom + margin;
	if (top < visibleTop + margin) return top - visibleTop - margin;
	return 0;
}

export function installInputVisibility() {
	const root = document.documentElement;
	const viewport = window.visualViewport;
	const telegram = window.Telegram?.WebApp;
	let baselineHeight = Math.max(
		window.innerHeight,
		viewport?.height || 0,
		telegram?.viewportHeight || 0,
	);
	let previousWidth = window.innerWidth;
	let frame = 0;
	let focusTimer: ReturnType<typeof setTimeout>;

	const activeInput = () => {
		const element = document.activeElement;
		return element instanceof HTMLElement &&
			element.matches(
				'input:not([readonly]):not([type=checkbox]):not([type=radio]),textarea,[contenteditable=true]',
			)
			? element
			: null;
	};

	const update = () => {
		const element = activeInput();
		const height = Math.min(
			viewport?.height || window.innerHeight,
			telegram?.viewportHeight || Infinity,
		);
		const offset = viewport?.offsetTop || 0;
		if (previousWidth !== window.innerWidth) {
			baselineHeight = window.innerHeight;
			previousWidth = window.innerWidth;
		}
		if (!element) baselineHeight = Math.max(baselineHeight, height);
		const keyboardOpen = !!element && baselineHeight - height > 120;
		root.dataset.keyboardOpen = String(keyboardOpen);
		root.style.setProperty('--visible-height', `${height}px`);
		root.style.setProperty('--visible-top', `${offset}px`);
		root.style.setProperty(
			'--keyboard-space',
			`${keyboardOpen ? Math.max(0, window.innerHeight - height - offset) : 0}px`,
		);
		if (!element || window.innerWidth > 900) return;
		const target =
			element.getBoundingClientRect().height < 10
				? element.closest<HTMLElement>('.ant-select') || element
				: element;
		const distance = () => {
			const bounds = target.getBoundingClientRect();
			return inputScrollDistance(bounds.top, bounds.bottom, offset, offset + height);
		};
		let parent = target.parentElement;
		while (parent && parent !== document.body) {
			if (
				parent.scrollHeight > parent.clientHeight &&
				/auto|scroll/.test(getComputedStyle(parent).overflowY)
			) {
				const delta = distance();
				if (Math.abs(delta) < 1) return;
				parent.scrollBy({ top: delta, behavior: 'instant' });
			}
			parent = parent.parentElement;
		}
		const delta = distance();
		if (Math.abs(delta) > 1) window.scrollBy({ top: delta, behavior: 'instant' });
	};
	const schedule = () => {
		cancelAnimationFrame(frame);
		frame = requestAnimationFrame(update);
	};
	const focusChanged = () => {
		schedule();
		clearTimeout(focusTimer);
		focusTimer = setTimeout(schedule, 250);
	};
	document.addEventListener('focusin', focusChanged);
	document.addEventListener('focusout', focusChanged);
	document.addEventListener('input', schedule);
	window.addEventListener('resize', schedule);
	viewport?.addEventListener('resize', schedule);
	viewport?.addEventListener('scroll', schedule);
	telegram?.onEvent('viewportChanged', schedule);
	schedule();
	return () => {
		clearTimeout(focusTimer);
		cancelAnimationFrame(frame);
		document.removeEventListener('focusin', focusChanged);
		document.removeEventListener('focusout', focusChanged);
		document.removeEventListener('input', schedule);
		window.removeEventListener('resize', schedule);
		viewport?.removeEventListener('resize', schedule);
		viewport?.removeEventListener('scroll', schedule);
		telegram?.offEvent('viewportChanged', schedule);
		delete root.dataset.keyboardOpen;
	};
}
