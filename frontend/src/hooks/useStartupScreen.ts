import { useEffect } from 'react';

export function useStartupScreen(ready: boolean) {
	useEffect(() => {
		const screen = document.getElementById('startup-screen');
		if (!ready || !screen) return;

		if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
			screen.remove();
			return;
		}

		let active = true;
		let removalTimer: number | undefined;
		const reveal = Promise.allSettled(
			(screen.getAnimations?.({ subtree: true }) ?? []).map((animation) => animation.finished),
		);
		void reveal.then(() => {
			if (!active) return;
			screen.classList.add('is-finished');
			screen.setAttribute('aria-hidden', 'true');
			removalTimer = window.setTimeout(() => screen.remove(), 340);
		});

		return () => {
			active = false;
			window.clearTimeout(removalTimer);
		};
	}, [ready]);
}
