import { theme, type ThemeConfig } from 'antd';

export function telegramTheme(dark: boolean): ThemeConfig {
	const colors = window.Telegram?.WebApp?.themeParams || {};
	const styles = getComputedStyle(document.documentElement);
	const token = (name: string) => styles.getPropertyValue('--kit-' + name).trim();
	const primary = colors.button_color || token('accent');
	const surface = colors.section_bg_color || colors.bg_color || token('bg');
	const background = colors.secondary_bg_color || token('page');
	const secondary = colors.subtitle_text_color || colors.hint_color || token('hint');
	const divider = colors.section_separator_color || token('divider');
	const radius = parseInt(token('control-radius'), 10);

	return {
		algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
		token: {
			colorPrimary: primary,
			colorInfo: primary,
			colorText: colors.text_color || token('text'),
			colorTextLightSolid: colors.button_text_color || token('button-text'),
			colorTextSecondary: secondary,
			colorTextPlaceholder: secondary,
			colorBgContainer: surface,
			colorBgElevated: surface,
			colorBgLayout: background,
			colorBorder: divider,
			colorBorderSecondary: divider,
			colorError: colors.destructive_text_color || token('destructive'),
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
