// Diagnostic components only. Never mutate physical/sensor/local-pose inputs.
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <gz/sim/EntityComponentManager.hh>
#include <gz/sim/World.hh>
#include <gz/sim/Model.hh>
#include <gz/sim/Util.hh>
#include <gz/sim/components/Name.hh>
#include <gz/sim/components/ParentEntity.hh>
#include <gz/sim/components/Pose.hh>
#include <gz/sim/components/LinearVelocity.hh>
#include <gz/sim/components/LinearAcceleration.hh>
#include <gz/sim/components/AngularVelocity.hh>
#include <gz/sim/components/World.hh>
#include <gz/sim/components/Model.hh>
#include <gz/sim/components/Link.hh>
#include <gz/sim/components/Sensor.hh>
namespace py=pybind11;
namespace c=gz::sim::components;
using ECM=gz::sim::EntityComponentManager;
using V=gz::math::Vector3d;
using P=gz::math::Pose3d;
using Q=gz::math::Quaterniond;

struct Probe {
  ECM *owner=nullptr;
  gz::sim::Entity parent=0,child=0;
  std::uint64_t last=0,epoch=0;
  bool failed=false,pending=false;
  static void require(bool valid,const char *message) {if(!valid) throw std::runtime_error(message);}
  template<class C> static C *get(ECM &e,gz::sim::Entity id) {
    auto p=e.Component<C>(id);require(p!=nullptr,"missing diagnostic component");return p;
  }
  template<class C> static const C *get(const ECM &e,gz::sim::Entity id) {
    auto p=e.Component<C>(id);require(p!=nullptr,"missing diagnostic component");return p;
  }
  void topology(const ECM &e) const {
    require(&e==owner,"ECM session changed");
    require(e.HasEntity(child)&&e.HasEntity(parent),"diagnostic entity missing");
    require(get<c::ParentEntity>(e,child)->Data()==parent,"diagnostic parent changed");
    require(!e.Component<c::Link>(child)&&!e.Component<c::Sensor>(child),"diagnostic became physical/sensor");
    auto p=get<c::Pose>(e,child)->Data();auto q=p.Rot();
    require(p.X()==0&&p.Y()==0&&p.Z()==0&&q.X()==0&&q.Y()==0&&q.Z()==0&&q.W()==1,"diagnostic local pose changed");
  }
  void pre(ECM &e,std::uint64_t ns,std::uint64_t dt) {
    try {
      require(!failed&&!pending&&dt==1000000&&ns==last+dt&&ns<=25000000000ULL,"native pre sequence");
      if(!owner) {
        owner=&e;auto world=gz::sim::worldEntity(e);
        auto model=gz::sim::World(world).ModelByName(e,"x500_benchmark_8");
        parent=gz::sim::Model(model).LinkByName(e,"base_link");
        require(world&&model&&parent,"diagnostic physical parent unavailable");
        child=e.CreateEntity();require(child&&e.SetParentEntity(child,parent),"diagnostic child creation failed");
        e.CreateComponent(child,c::Name("fly_native_reference_child"));
        e.CreateComponent(child,c::ParentEntity(parent));
        e.CreateComponent(child,c::Pose(P::Zero));
        e.CreateComponent(child,c::WorldPose(P::Zero));
        e.CreateComponent(child,c::WorldLinearVelocity(V::Zero));
        e.CreateComponent(child,c::WorldLinearAcceleration(V::Zero));
        e.CreateComponent(child,c::WorldAngularVelocity(V::Zero));
      }
      topology(e);
      auto n=std::numeric_limits<double>::quiet_NaN();V nv(n,n,n);
      get<c::WorldPose>(e,child)->Data()=P(nv,Q(n,n,n,n));
      get<c::WorldLinearVelocity>(e,child)->Data()=nv;
      get<c::WorldLinearAcceleration>(e,child)->Data()=nv;
      get<c::WorldAngularVelocity>(e,child)->Data()=nv;
      epoch=ns;pending=true;
    } catch(...) {failed=true;throw;}
  }
  static std::array<double,3> xyz(const V &v) {
    require(std::isfinite(v.X())&&std::isfinite(v.Y())&&std::isfinite(v.Z()),"native canary/nonfinite output");
    return {v.X(),v.Y(),v.Z()};
  }
  py::dict post(const ECM &e,std::uint64_t ns) {
    try {
      require(!failed&&pending&&epoch==ns,"native post sequence");topology(e);
      auto p=get<c::WorldPose>(e,child)->Data();auto q=p.Rot();
      auto position=xyz(p.Pos());auto velocity=xyz(get<c::WorldLinearVelocity>(e,child)->Data());
      auto accel=xyz(get<c::WorldLinearAcceleration>(e,child)->Data());
      auto angular=xyz(get<c::WorldAngularVelocity>(e,child)->Data());
      std::array<double,4> quat={q.X(),q.Y(),q.Z(),q.W()};double sum=0;
      for(double v:quat){require(std::isfinite(v),"native quaternion canary");sum+=v*v;}
      require(std::isfinite(sum)&&std::abs(sum-1)<=1e-6,"native nonunit quaternion");
      auto rpy=xyz(q.Euler());
      py::dict out;out["position"]=position;out["velocity_world"]=velocity;out["accel_world"]=accel;
      out["angular_world"]=angular;out["quaternion_xyzw"]=quat;out["rpy"]=rpy;
      out["parent_entity"]=parent;out["child_entity"]=child;out["pre_ns"]=epoch;out["post_ns"]=ns;
      out["canary_overwritten"]=true;last=ns;pending=false;return out;
    } catch(...) {failed=true;throw;}
  }
  py::dict status() const {py::dict r;r["failed"]=failed;r["pending"]=pending;r["last_ns"]=last;return r;}
#ifdef FLY_REFERENCE_TESTING
  void inject(ECM &e,const std::string &mode) {
    require(pending,"test injection needs pending epoch");
    get<c::WorldPose>(e,child)->Data()=P(0,0,.2,0,0,0);
    get<c::WorldLinearVelocity>(e,child)->Data()=V::Zero;
    get<c::WorldAngularVelocity>(e,child)->Data()=V::Zero;
    if(mode!="partial") get<c::WorldLinearAcceleration>(e,child)->Data()=V::Zero;
    if(mode=="quaternion")get<c::WorldPose>(e,child)->Data()=P(V::Zero,Q(0,0,0,0));
    if(mode=="topology")get<c::ParentEntity>(e,child)->Data()=999999;
  }
#endif
};
#ifdef FLY_REFERENCE_TESTING
PYBIND11_MODULE(_fly_native_reference_test,m) {
#else
PYBIND11_MODULE(_fly_native_reference,m) {
#endif
  m.attr("API_VERSION")=1;
  auto type=py::class_<Probe>(m,"Probe",py::module_local()).def(py::init<>()).def("pre",&Probe::pre).def("post",&Probe::post).def("status",&Probe::status);
#ifdef FLY_REFERENCE_TESTING
  m.attr("TESTING")=true;type.def("inject",&Probe::inject);
  m.def("fixture",[](ECM &e) {
    auto w=e.CreateEntity();e.CreateComponent(w,c::World());e.CreateComponent(w,c::Name("test"));
    auto m=e.CreateEntity();e.SetParentEntity(m,w);e.CreateComponent(m,c::Model());e.CreateComponent(m,c::Name("x500_benchmark_8"));e.CreateComponent(m,c::ParentEntity(w));
    auto l=e.CreateEntity();e.SetParentEntity(l,m);e.CreateComponent(l,c::Link());e.CreateComponent(l,c::Name("base_link"));e.CreateComponent(l,c::ParentEntity(m));
  });
#else
  m.attr("TESTING")=false;
#endif
}
