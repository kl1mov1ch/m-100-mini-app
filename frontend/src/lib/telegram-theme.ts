import type { ThemeConfig } from 'antd';

export const telegramLightBackground = '#efeff4';

export const telegramLightTheme: ThemeConfig = {
	token: {
		colorPrimary: '#0068d7',
		colorInfo: '#0068d7',
		colorText: '#18181a',
		colorTextSecondary: '#636366',
		colorTextPlaceholder: '#707075',
		colorBorder: '#d8d8de',
		colorBorderSecondary: '#e5e5ea',
		colorBgContainer: '#ffffff',
		colorBgElevated: '#ffffff',
		colorBgLayout: telegramLightBackground,
		colorSuccess: '#187943',
		colorWarning: '#654388',
		colorError: '#bd252d',
		borderRadius: 10,
		borderRadiusLG: 14,
		fontFamily: 'var(--ios-font)',
		fontSize: 15,
		controlHeight: 44,
		controlHeightLG: 50,
	},
	components: {
		Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 600 },
		InputNumber: { controlWidth: 100 },
		Segmented: { trackBg: '#e9e9ee', itemSelectedBg: '#ffffff', trackPadding: 3 },
		Switch: { colorPrimary: '#208848', colorPrimaryHover: '#187943' },
		Select: { optionSelectedBg: '#e8f2ff' },
	},
};
