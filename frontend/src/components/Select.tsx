import { Select as AntSelect, type SelectProps } from 'antd';
import type { DefaultOptionType } from 'antd/es/select';
import { ChevronDown } from './kit-icons';

export function Select<Value>({ className = '', ...props }: SelectProps<Value, DefaultOptionType>) {
	return (
		<AntSelect
			className={`journal-select ${className}`}
			suffixIcon={<ChevronDown size={16} />}
			getPopupContainer={() => document.getElementById('miniapp-surface') ?? document.body}
			{...props}
		/>
	);
}
