import { ChevronDown, ChevronLeft, ChevronRight, X } from './kit-icons';

type IconName =
	| 'calendar'
	| 'check'
	| 'chevron-down'
	| 'chevron-left'
	| 'chevron-right'
	| 'close'
	| 'folder'
	| 'report'
	| 'search';

const providedIcons: Partial<Record<IconName, typeof X>> = {
	'chevron-down': ChevronDown,
	'chevron-left': ChevronLeft,
	'chevron-right': ChevronRight,
	close: X,
};

export function TelegramIcon({ name, size = 24 }: { name: IconName; size?: number }) {
	const Icon = providedIcons[name];
	if (Icon) return <Icon size={size} />;
	return (
		<svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
			<use href={`/brand/telegram-icons.svg#${name}`} stroke="none" />
		</svg>
	);
}
