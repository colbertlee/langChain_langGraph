import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ToolCallCard } from './tool-fallback';

describe('ToolCallCard', () => {
  it('显示工具名', () => {
    render(<ToolCallCard toolName="get_weather" args={{ city: 'Beijing' }} />);
    expect(screen.getByText('get_weather')).toBeInTheDocument();
  });

  it('折叠时不显示 args', () => {
    render(<ToolCallCard toolName="get_weather" args={{ city: 'Beijing' }} />);
    expect(screen.queryByText(/Beijing/)).not.toBeInTheDocument();
  });

  it('点击展开后显示 Arguments / Result', () => {
    render(
      <ToolCallCard
        toolName="run_code"
        args={{ code: 'print(1)' }}
        result="1\n"
        status={{ type: 'complete' }}
      />,
    );
    fireEvent.click(screen.getByText('run_code'));
    expect(screen.getByText('Arguments')).toBeInTheDocument();
    expect(screen.getByText('Result')).toBeInTheDocument();
    expect(screen.getByText(/print\(1\)/)).toBeInTheDocument();
  });

  it('running 状态显示加载图标', () => {
    const { container } = render(
      <ToolCallCard toolName="search" args={{}} status={{ type: 'running' }} />,
    );
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('error / incomplete 状态显示错误图标', () => {
    const { container } = render(
      <ToolCallCard toolName="search" args={{}} status={{ type: 'incomplete' }} />,
    );
    expect(container.querySelector('.text-danger, .text-\\[var\\(--danger\\)\\]')).toBeTruthy();
  });
});
