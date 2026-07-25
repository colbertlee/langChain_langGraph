import { describe, it, expect } from 'vitest';
import { SUPPORTED_LANGS, isSupportedLang } from './syntaxLanguages';

describe('syntaxLanguages', () => {
  it('SUPPORTED_LANGS 是 ReadonlySet', () => {
    expect(SUPPORTED_LANGS).toBeInstanceOf(Set);
  });

  it('包含主要语言的标准名', () => {
    for (const lang of ['javascript', 'typescript', 'python', 'bash', 'json', 'css', 'sql', 'yaml', 'markdown', 'go', 'rust', 'java', 'cpp']) {
      expect(SUPPORTED_LANGS.has(lang), lang).toBe(true);
    }
  });

  it('包含常用别名', () => {
    for (const alias of ['js', 'ts', 'py', 'sh', 'yml', 'md', 'rs', 'c', 'html', 'vue']) {
      expect(SUPPORTED_LANGS.has(alias), alias).toBe(true);
    }
  });

  it('isSupportedLang 返回正确布尔', () => {
    expect(isSupportedLang('typescript')).toBe(true);
    expect(isSupportedLang('kotlin')).toBe(false);
    expect(isSupportedLang('xyz')).toBe(false);
  });

  it('未注册的语言不会抛错', () => {
    expect(() => isSupportedLang('not-a-language')).not.toThrow();
  });
});