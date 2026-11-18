import { Input as TelegramInput, Textarea } from '@telegram-apps/telegram-ui';
import { Input as AntInput } from 'antd';
import { useLayoutEffect, useRef, type ComponentPropsWithoutRef, type ReactNode } from 'react';

type TextAreaProps = ComponentPropsWithoutRef<'textarea'> & {
	autoSize?: boolean | { minRows?: number; maxRows?: number };
};
type InputProps = Omit<ComponentPropsWithoutRef<'input'>, 'prefix' | 'size'> & {
	allowClear?: boolean;
	prefix?: ReactNode;
};

function TextArea({ autoSize, rows, value, ...props }: TextAreaProps) {
	const field = useRef<HTMLTextAreaElement>(null);
	useLayoutEffect(() => {
		const element = field.current;
		if (!autoSize || !element) return;
		element.style.height = 'auto';
		const lineHeight = parseFloat(getComputedStyle(element).lineHeight) || 24;
		const config = typeof autoSize === 'object' ? autoSize : {};
		const max = config.maxRows ? config.maxRows * lineHeight : Infinity;
		element.style.height = Math.min(max, element.scrollHeight) + 'px';
	}, [autoSize, value]);
	return (
		<Textarea
			{...props}
			ref={field}
			value={value}
			rows={rows ?? (typeof autoSize === 'object' ? autoSize.minRows : undefined)}
		/>
	);
}

export function Input({ allowClear, prefix, ...props }: InputProps) {
	if (allowClear) return <AntInput {...props} prefix={prefix} allowClear />;
	return <TelegramInput {...props} before={prefix} />;
}

Input.TextArea = TextArea;
Input.Password = AntInput.Password;
