import { Button as TelegramButton } from '@telegram-apps/telegram-ui';
import type { ButtonProps } from 'antd';
import type { MouseEventHandler } from 'react';

export function Button({
	type = 'default',
	size,
	icon,
	block,
	danger,
	loading,
	className = '',
	disabled,
	href,
	htmlType,
	onClick,
	children,
	...props
}: ButtonProps) {
	const mode = type === 'primary' ? 'filled' : 'plain';
	const label = props['aria-label'] || (typeof children === 'string' ? children.trim() : '');
	const iconOnly =
		type === 'default' && !!icon && !!label && (children == null || typeof children === 'string');
	return (
		<TelegramButton
			{...props}
			className={[
				'm100-button',
				iconOnly ? 'journal-icon-action' : '',
				'ant-btn',
				'ant-btn-' + type,
				size === 'small' ? 'ant-btn-sm' : size === 'large' ? 'ant-btn-lg' : '',
				danger ? 'ant-btn-dangerous' : '',
				className,
			]
				.filter(Boolean)
				.join(' ')}
			Component={href ? 'a' : 'button'}
			mode={mode}
			size={size === 'small' ? 's' : size === 'large' ? 'l' : 'm'}
			stretched={block}
			before={iconOnly ? undefined : icon}
			aria-label={iconOnly ? label : props['aria-label']}
			title={props.title || (iconOnly ? label : undefined)}
			loading={Boolean(loading)}
			disabled={!href && (disabled || Boolean(loading))}
			aria-disabled={href && (disabled || Boolean(loading)) ? true : props['aria-disabled']}
			href={disabled || loading ? undefined : href}
			type={htmlType}
			onClick={(event) => {
				if (disabled || loading) {
					event.preventDefault();
					return;
				}
				(onClick as MouseEventHandler<HTMLButtonElement> | undefined)?.(event);
			}}
		>
			{iconOnly ? icon : children}
		</TelegramButton>
	);
}
