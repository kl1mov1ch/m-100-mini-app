import { Icon24ChevronDown } from '@telegram-apps/telegram-ui/dist/icons/24/chevron_down';
import { Icon24ChevronLeft } from '@telegram-apps/telegram-ui/dist/icons/24/chevron_left';
import { Icon24ChevronRight } from '@telegram-apps/telegram-ui/dist/icons/24/chevron_right';
import { Icon24Close } from '@telegram-apps/telegram-ui/dist/icons/24/close';
import { Icon24Notifications } from '@telegram-apps/telegram-ui/dist/icons/24/notifications';
import { Icon28Attach } from '@telegram-apps/telegram-ui/dist/icons/28/attach';
import { Icon28Heart } from '@telegram-apps/telegram-ui/dist/icons/28/heart';
import type { ComponentType, SVGProps } from 'react';

type Props = SVGProps<SVGSVGElement> & { size?: number | string };

function icon(Component: ComponentType<SVGProps<SVGSVGElement>>, grid = 24) {
	return function KitIcon({ size = grid, ...props }: Props) {
		return (
			<Component
				viewBox={`0 0 ${grid} ${grid}`}
				width={size}
				height={size}
				aria-hidden
				{...props}
			/>
		);
	};
}

export const ChevronDown = icon(Icon24ChevronDown);
export const ChevronLeft = icon(Icon24ChevronLeft);
export const ChevronRight = icon(Icon24ChevronRight);
export const X = icon(Icon24Close);
export const Bell = icon(Icon24Notifications);
export const Paperclip = icon(Icon28Attach, 28);
export const Heart = icon(Icon28Heart, 28);
