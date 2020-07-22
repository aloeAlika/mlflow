import React from 'react';
import { shallow, mount } from 'enzyme';
import { ModelVersionView } from './ModelVersionView';
import { mockModelVersionDetailed } from '../test-utils';
import { Stages, ModelVersionStatus, ACTIVE_STAGES } from '../constants';
import { Dropdown, Tooltip } from 'antd';
import { BrowserRouter } from 'react-router-dom';
import Utils from '../../common/utils/Utils';
import { mockRunInfo } from '../../experiment-tracking/utils/test-utils/ReduxStoreFixtures';
import Routers from '../../experiment-tracking/routes';

describe('ModelVersionView', () => {
  let wrapper;
  let minimalProps;

  beforeEach(() => {
    minimalProps = {
      modelName: 'Model A',
      modelVersion: mockModelVersionDetailed(
        'Model A',
        1,
        Stages.PRODUCTION,
        ModelVersionStatus.READY,
        [],
      ),
      handleStageTransitionDropdownSelect: jest.fn(),
      handlePendingRequestTransition: jest.fn(),
      handlePendingRequestDeletion: jest.fn(),
      deleteModelVersionApi: jest.fn(() => Promise.resolve()),
      handleEditDescription: jest.fn(() => Promise.resolve()),
      history: { push: jest.fn() },
    };
  });

  test('should render with minimal props without exploding', () => {
    wrapper = shallow(<ModelVersionView {...minimalProps} />);
    expect(wrapper.length).toBe(1);
  });

  test('should render delete dropdown item when model version is ready', () => {
    const props = {
      ...minimalProps,
      modelVersion: mockModelVersionDetailed(
        'Model A',
        1,
        Stages.NONE,
        ModelVersionStatus.READY,
        [],
      ),
    };
    wrapper = mount(
      <BrowserRouter>
        <ModelVersionView {...props} />
      </BrowserRouter>,
    );
    expect(wrapper.find('.breadcrumb-header').find(Dropdown).length).toBe(1);
  });

  test('should disable dropdown delete menu item when model version is in active stage', () => {
    let i;
    for (i = 0; i < ACTIVE_STAGES.length; ++i) {
      const props = {
        ...minimalProps,
        modelVersion: mockModelVersionDetailed(
          'Model A',
          1,
          ACTIVE_STAGES[i],
          ModelVersionStatus.READY,
          [],
        ),
      };
      wrapper = mount(
        <BrowserRouter>
          <ModelVersionView {...props} />
        </BrowserRouter>,
      );
      wrapper
        .find('.breadcrumb-dropdown')
        .hostNodes()
        .simulate('click');
      // The antd `Menu.Item` component converts the `disabled` attribute to `aria-disabled`
      // when generating HTML. Accordingly, we check for the presence of the `aria-disabled`
      // attribute within the rendered HTML.
      const deleteMenuItem = wrapper.find('.delete').hostNodes();
      expect(deleteMenuItem.prop('aria-disabled')).toBe(true);
      deleteMenuItem.simulate('click');
      expect(wrapper.find(ModelVersionView).instance().state.isDeleteModalVisible).toBe(false);
    }
  });

  test('should place tooltip on the right', () => {
    let i;
    for (i = 0; i < ACTIVE_STAGES.length; ++i) {
      const props = {
        ...minimalProps,
        modelVersion: mockModelVersionDetailed(
          'Model A',
          1,
          ACTIVE_STAGES[i],
          ModelVersionStatus.READY,
          [],
        ),
      };
      wrapper = mount(
        <BrowserRouter>
          <ModelVersionView {...props} />
        </BrowserRouter>,
      );
      wrapper
        .find('.breadcrumb-dropdown')
        .hostNodes()
        .simulate('click');
      const deleteMenuItem = wrapper.find('.delete').hostNodes();
      const tooltip = deleteMenuItem.find(Tooltip);
      expect(tooltip.prop('placement')).toBe('right');
    }
  });

  test('should enable dropdown delete menu item when model version is in active stage', () => {
    const inactiveStages = [Stages.NONE, Stages.ARCHIVED];
    let i;
    for (i = 0; i < inactiveStages.length; ++i) {
      const props = {
        ...minimalProps,
        modelVersion: mockModelVersionDetailed(
          'Model A',
          1,
          inactiveStages[i],
          ModelVersionStatus.READY,
          [],
        ),
      };
      wrapper = mount(
        <BrowserRouter>
          <ModelVersionView {...props} />
        </BrowserRouter>,
      );
      wrapper
        .find('.breadcrumb-dropdown')
        .hostNodes()
        .simulate('click');
      // The antd `Menu.Item` component converts the `disabled` attribute to `aria-disabled`
      // when generating HTML. Accordingly, we check for the presence of the `aria-disabled`
      // attribute within the rendered HTML.
      const deleteMenuItem = wrapper.find('.delete').hostNodes();
      expect(deleteMenuItem.prop('aria-disabled')).toBeUndefined();
      deleteMenuItem.simulate('click');
      expect(wrapper.find(ModelVersionView).instance().state.isDeleteModalVisible).toBe(true);
    }
  });

  test('run link renders if set', () => {
    const modelVersion = mockModelVersionDetailed(
      'Model A',
      1,
      Stages.NONE,
      ModelVersionStatus.READY,
      [],
    );
    const runLink =
      'https://other.mlflow.hosted.instance.com/experiments/18722387/' +
      'runs/d2c09dbd056c4d9c9289b854f491be10';
    modelVersion['runLink'] = runLink;
    const runId = 'somerunid';
    const experimentId = 'experiment_id';
    const runInfo = mockRunInfo(runId, experimentId);
    const expectedRunDisplayName = Utils.getRunDisplayName({}, runId);
    const props = {
      ...minimalProps,
      modelVersion: modelVersion,
      runInfo: runInfo,
      runDisplayName: expectedRunDisplayName,
    };
    wrapper = mount(
      <BrowserRouter>
        <ModelVersionView {...props} />
      </BrowserRouter>,
    );
    expect(wrapper.find('.linked-run').html()).toContain(runLink);
    expect(wrapper.find('.linked-run').html()).toContain(runLink.substr(0, 37) + '...');
  });

  test('run name and link render if runinfo provided', () => {
    const runId = 'somerunid';
    const experimentId = 'experiment_id';
    const runInfo = mockRunInfo(runId, experimentId);
    const expectedRunLink = Routers.getRunPageRoute(experimentId, runId);
    const expectedRunDisplayName = Utils.getRunDisplayName({}, runId);
    const props = {
      ...minimalProps,
      runInfo: runInfo,
      runDisplayName: expectedRunDisplayName,
    };
    wrapper = mount(
      <BrowserRouter>
        <ModelVersionView {...props} />
      </BrowserRouter>,
    );
    expect(wrapper.find('.linked-run').html()).toContain(expectedRunLink);
    expect(wrapper.find('.linked-run').html()).toContain(expectedRunDisplayName);
  });

  test('Page title is set', () => {
    const mockUpdatePageTitle = jest.fn();
    Utils.updatePageTitle = mockUpdatePageTitle;
    wrapper = shallow(<ModelVersionView {...minimalProps} />);
    expect(mockUpdatePageTitle.mock.calls[0][0]).toBe('Model A v1 - MLflow Model');
  });
});
