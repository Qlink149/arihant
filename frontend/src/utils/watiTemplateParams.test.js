import { parseTemplateVariables, buildTemplateParameters } from './watiTemplateParams';

describe('parseTemplateVariables', () => {
  it('uses custom_params when present', () => {
    const vars = parseTemplateVariables(
      {
        custom_params: [
          { name: 'name', value: '' },
          { name: 'project', value: '' },
        ],
      },
      { name: 'Priya', project: 'Vivriti' }
    );
    expect(vars).toHaveLength(2);
    expect(vars[0].defaultValue).toBe('Priya');
    expect(vars[1].defaultValue).toBe('Vivriti');
  });

  it('parses positional placeholders from body', () => {
    const vars = parseTemplateVariables(
      { body: 'Hi {{1}}, welcome to {{2}}' },
      { name: 'A', project: 'B' }
    );
    expect(vars.map((v) => v.name)).toEqual(['1', '2']);
    expect(vars[0].defaultValue).toBe('A');
    expect(vars[1].defaultValue).toBe('B');
  });

  it('buildTemplateParameters maps edited values', () => {
    const vars = parseTemplateVariables({ custom_params: [{ name: 'name' }] }, {});
    expect(buildTemplateParameters(vars, { name: 'X' })).toEqual([{ name: 'name', value: 'X' }]);
  });

  it('returns one free-text fallback when no params or placeholders', () => {
    const vars = parseTemplateVariables({ body: 'Hello there' }, { name: 'Sam' });
    expect(vars).toHaveLength(1);
    expect(vars[0].name).toBe('name');
    expect(vars[0].defaultValue).toBe('Sam');
  });
});
