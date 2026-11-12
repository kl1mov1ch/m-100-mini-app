import { useEffect, useEffectEvent, useRef } from 'react';
import type { ObjectSection } from '../types';

declare const __APP_RELEASE__: string;

type ReleaseNavigation = {
	page: string;
	project: string;
	day: string;
	objectSection: ObjectSection;
};

const navigationKey = 'app-release-navigation';
const attemptKey = 'app-release-attempt';

export function takeReleaseNavigation(): ReleaseNavigation | undefined {
	try {
		const raw = sessionStorage.getItem(navigationKey);
		if (raw) {
			sessionStorage.removeItem(navigationKey);
			return JSON.parse(raw) as ReleaseNavigation;
		}
	} catch {
		return undefined;
	}
}

export function useAppRelease(blocked: boolean, navigation: ReleaseNavigation) {
	const available = useRef<string | null>(null);
	const tryReload = useEffectEvent(() => {
		const version = available.current;
		if (!version || blocked || document.hidden) return;
		if (document.activeElement?.matches('input, textarea, select, [contenteditable="true"]'))
			return;
		if (
			Array.from(document.querySelectorAll('.ant-modal-wrap, .ant-drawer-content-wrapper')).some(
				(element) => element.getClientRects().length > 0,
			)
		)
			return;
		available.current = null;
		try {
			if (sessionStorage.getItem(attemptKey) === version) return;
			sessionStorage.setItem(attemptKey, version);
			sessionStorage.setItem(navigationKey, JSON.stringify(navigation));
		} catch {
			return;
		}
		window.location.reload();
	});
	useEffect(() => {
		tryReload();
	}, [blocked]);
	useEffect(() => {
		if (__APP_RELEASE__ === 'development') return;
		let active = true;
		const check = async () => {
			if (document.hidden) return;
			try {
				const response = await fetch('/app-release.json', { cache: 'no-store' });
				if (!response.ok || !active) return;
				const { release } = await response.json();
				if (!active) return;
				available.current =
					typeof release === 'string' && release !== __APP_RELEASE__ ? release : null;
				tryReload();
			} catch {
				return;
			}
		};
		void check();
		const afterFocus = () =>
			window.setTimeout(() => {
				if (active) tryReload();
			}, 0);
		const timer = window.setInterval(check, 30000);
		document.addEventListener('visibilitychange', check);
		window.addEventListener('online', check);
		window.addEventListener('focus', check);
		document.addEventListener('focusout', afterFocus);
		return () => {
			active = false;
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', check);
			window.removeEventListener('online', check);
			window.removeEventListener('focus', check);
			document.removeEventListener('focusout', afterFocus);
		};
	}, []);
}
