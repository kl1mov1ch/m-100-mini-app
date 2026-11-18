import { useEffectEvent } from './useEffectEvent';
import { useEffect } from 'react';

export function useTelegramNavigation(back: (() => void) | undefined, unsaved: boolean): void {
	const handleBack = useEffectEvent(() => back?.());
	const canGoBack = Boolean(back);
	useEffect(() => {
		const app = window.Telegram?.WebApp;
		if (!app?.initData || !app.isVersionAtLeast('6.1')) return;
		if (!canGoBack) {
			app.BackButton.hide();
			return;
		}
		app.BackButton.show();
		const onBack = () => handleBack();
		app.BackButton.onClick(onBack);
		return () => {
			app.BackButton.offClick(onBack);
			app.BackButton.hide();
		};
	}, [canGoBack]);
	useEffect(() => {
		const app = window.Telegram?.WebApp;
		if (!app?.initData || !app.isVersionAtLeast('6.2')) return;
		if (unsaved) app.enableClosingConfirmation();
		else app.disableClosingConfirmation();
		return () => app.disableClosingConfirmation();
	}, [unsaved]);
}
