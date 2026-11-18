import { Select as TelegramSelect } from '@telegram-apps/telegram-ui';
import { Select as AntSelect, type SelectProps } from 'antd';
import type { DefaultOptionType } from 'antd/es/select';

export function Select<Value>({ options, ...props }: SelectProps<Value, DefaultOptionType>) {
	const simpleOptions = options?.every(
		(option) =>
			(typeof option.value === 'string' || typeof option.value === 'number') &&
			typeof option.label === 'string' &&
			!option.options,
	);
	if (
		!simpleOptions ||
		props.mode ||
		props.showSearch ||
		props.allowClear ||
		props.filterSort ||
		props.filterOption !== undefined ||
		props.classNames
	) {
		return <AntSelect {...props} options={options} />;
	}

	const current = options?.findIndex((option) => option.value === props.value) ?? -1;
	return (
		<TelegramSelect
			id={props.id}
			className={props.className}
			aria-label={props['aria-label']}
			aria-required={props['aria-required']}
			disabled={props.disabled}
			autoFocus={props.autoFocus}
			value={current < 0 ? '' : String(current)}
			onChange={(event) => {
				const option = options?.[Number(event.target.value)];
				if (option) props.onChange?.(option.value as Value, option);
			}}
		>
			<option disabled hidden value="">
				{props.placeholder || 'Выберите значение'}
			</option>
			{options?.map((option, index) => (
				<option key={option.value} value={index} disabled={option.disabled}>
					{option.label}
				</option>
			))}
		</TelegramSelect>
	);
}
