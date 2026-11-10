import { useEffect } from 'react';
import { installInputVisibility } from '../lib/input-visibility';

export function useInputVisibility() {
	useEffect(installInputVisibility, []);
}
