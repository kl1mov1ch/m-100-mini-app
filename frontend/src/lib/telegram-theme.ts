import type { ThemeConfig } from 'antd';

export function telegramTheme(): ThemeConfig {
	const styles = getComputedStyle(document.documentElement);
	const token = (name: string) => styles.getPropertyValue('--kit-' + name).trim();
	const primary = token('accent');
	const surface = token('bg');
	const background = token('page');
	const secondary = token('hint');
	const divider = token('divider');
	const radius = parseInt(token('control-radius'), 10);

	return {
		token: {
			colorPrimary: primary,
			colorInfo: primary,
			colorText: token('text'),
			colorTextLightSolid: token('button-text'),
			colorTextSecondary: secondary,
			colorTextPlaceholder: secondary,
			colorBgContainer: surface,
			colorBgElevated: surface,
			colorBgLayout: background,
			colorBorder: divider,
			colorBorderSecondary: divider,
			colorError: token('destructive'),
			colorSuccess: token('green'),
			borderRadius: radius,
			fontFamily: 'var(--ios-font)',
			fontSize: parseInt(token('body'), 10),
			controlHeight: parseInt(token('touch'), 10),
			controlHeightLG: parseInt(token('large-button'), 10),
		},
		components: {
			Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 600 },
			InputNumber: { controlWidth: 100 },
			Switch: { colorPrimary: primary },
			Segmented: {
				trackBg: token('tertiary'),
				itemSelectedBg: token('segment-active'),
				trackPadding: 2,
			},
			Select: { optionSelectedBg: token('secondary-fill') },
		},
	};
}
